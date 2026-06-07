"""Read-only, org-scoped tools for the adaptive retrieval loop (Phase 6, 06 §4).

The single agent gathers evidence by calling these — and ONLY these — tools. Every tool:

- enforces ``org_id`` **server-side** from the tenancy seam; the model never supplies it, so
  a cross-org id simply finds nothing (deny, no existence leak);
- is **read-only** — no destructive or external-action tool ever enters the answer loop
  (CLAUDE.md); and
- in a customer-facing (respond-mode) answer, returns only ``customer_shareable`` content, so
  internal-only material can't enter a customer answer even mid-loop.

Tool *results* are untrusted DATA fed back to the model as tool-result messages — never
system instructions (06 §7). The loop control + audit live in the answer path.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Finding, KnowledgeChunk, Organization
from ..providers import ToolCall, ToolSpec
from ..retrieval import RetrievalFilters, RetrievedChunk, retrieve
from .schema import CitedEvidence

SEARCH_EVIDENCE = "search_evidence"
GET_POLICY = "get_policy"
GET_CONTROL = "get_control"
GET_FINDINGS = "get_findings"

# Bound each tool result fed back into the model context.
_SNIPPET_CHARS = 1500
_MAX_RESULTS = 8

# The retrieval tools offered to the agent (the provider adds its own emit_answer_draft tool
# for structured-output termination). org_id is deliberately ABSENT from every schema.
TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name=SEARCH_EVIDENCE,
        description=(
            "Hybrid search (vector + keyword, reranked) over the organization's own "
            "evidence: policies, controls, attestations, prior approved answers. Reformulate "
            "the query with synonyms when a first search misses (e.g. 'background checks' -> "
            "'personnel security / pre-employment screening / HR security'). Returns ranked "
            "chunks; cite them by their `ref`."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query."},
                "source_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional filter: policy | control | evidence | approved_answer | "
                        "company_profile."
                    ),
                },
                "confidentiality": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional confidentiality filter (e.g. public).",
                },
            },
            "required": ["query"],
        },
    ),
    ToolSpec(
        name=GET_POLICY,
        description="Fetch a specific policy document's text by its id (from a search result's source_id).",
        input_schema={
            "type": "object",
            "properties": {"id": {"type": "string", "description": "The policy document id."}},
            "required": ["id"],
        },
    ),
    ToolSpec(
        name=GET_CONTROL,
        description="Fetch a specific control's text by its id (from a search result's source_id).",
        input_schema={
            "type": "object",
            "properties": {"id": {"type": "string", "description": "The control id."}},
            "required": ["id"],
        },
    ),
    ToolSpec(
        name=GET_FINDINGS,
        description=(
            "Fetch the remediation-register entries (status, dates) for a provided report "
            "(e.g. a pentest) by its document id."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "document_id": {"type": "string", "description": "The report's document id."}
            },
            "required": ["document_id"],
        },
    ),
)


def _as_uuid(raw: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError):
        return None


def _str_list(value: object) -> list[str] | None:
    if not isinstance(value, (list, tuple)):
        return None
    items = [str(v) for v in value if isinstance(v, (str, int))]
    return items or None


def _cited_from_retrieved(rc: RetrievedChunk) -> CitedEvidence:
    meta = rc.meta or {}
    return CitedEvidence(
        chunk_id=str(rc.chunk_id),
        source_type=rc.source_type,
        source_id=str(rc.source_id) if rc.source_id else None,
        title=meta.get("title") or meta.get("control_code") or rc.source_type,
        text=rc.chunk_text,
        customer_shareable=bool(meta.get("customer_shareable", False)),
        confidentiality=meta.get("confidentiality", "internal"),
        rerank_score=rc.rerank_score,
        fusion_score=rc.fusion_score,
    )


def _cited_from_chunk_row(chunk: KnowledgeChunk) -> CitedEvidence:
    meta = chunk.meta or {}
    return CitedEvidence(
        chunk_id=str(chunk.id),
        source_type=chunk.source_type,
        source_id=str(chunk.source_id) if chunk.source_id else None,
        title=meta.get("title") or meta.get("control_code") or chunk.source_type,
        text=chunk.chunk_text,
        customer_shareable=bool(meta.get("customer_shareable", False)),
        confidentiality=meta.get("confidentiality", "internal"),
        rerank_score=0.0,
        fusion_score=0.0,
    )


def _model_view(c: CitedEvidence) -> dict:
    return {
        "ref": c.chunk_id,
        "source_type": c.source_type,
        "source_id": c.source_id,
        "title": c.title,
        "text": c.text[:_SNIPPET_CHARS],
    }


def _search_evidence(
    session: Session, org: Organization, args: dict, *, customer_facing: bool, top_k: int
) -> tuple[dict, list[CitedEvidence]]:
    query = str(args.get("query") or "").strip()
    if not query:
        return {"error": "query is required"}, []
    filters = RetrievalFilters(
        org_id=org.id,  # SERVER-enforced; the model never supplies the org
        source_types=_str_list(args.get("source_types")),
        confidentiality=_str_list(args.get("confidentiality")),
        # Respond mode is customer-facing: hard-gate to shareable, never widened by the model.
        customer_shareable=True if customer_facing else args.get("customer_shareable"),
    )
    chunks = retrieve(session, query=query, filters=filters, top_k=top_k)
    cited = [_cited_from_retrieved(rc) for rc in chunks[:_MAX_RESULTS]]
    return {"results": [_model_view(c) for c in cited]}, cited


def _get_doc_chunks(
    session: Session,
    org: Organization,
    raw_id: object,
    source_type: str,
    *,
    customer_facing: bool,
) -> tuple[dict, list[CitedEvidence]]:
    doc_id = _as_uuid(raw_id)
    if doc_id is None:
        return {"error": "invalid id"}, []
    chunks = list(
        session.scalars(
            select(KnowledgeChunk)
            .where(
                KnowledgeChunk.org_id == org.id,  # SERVER-enforced tenancy
                KnowledgeChunk.source_type == source_type,
                KnowledgeChunk.source_id == doc_id,
            )
            .order_by(KnowledgeChunk.chunk_index)
        ).all()
    )
    if customer_facing:
        chunks = [c for c in chunks if (c.meta or {}).get("customer_shareable")]
    if not chunks:
        # Cross-org, unknown, or not shareable — indistinguishable (default deny, no leak).
        return {"found": False}, []
    cited = [_cited_from_chunk_row(c) for c in chunks]
    title = (chunks[0].meta or {}).get("title") or source_type
    return (
        {"found": True, "id": str(doc_id), "title": title, "chunks": [_model_view(c) for c in cited]},
        cited,
    )


def _get_findings(
    session: Session, org: Organization, raw_id: object, *, customer_facing: bool
) -> tuple[dict, list[CitedEvidence]]:
    doc_id = _as_uuid(raw_id)
    if doc_id is None:
        return {"error": "invalid document_id"}, []
    stmt = select(Finding).where(
        Finding.org_id == org.id,  # SERVER-enforced tenancy
        Finding.source_document_id == doc_id,
    )
    if customer_facing:
        stmt = stmt.where(Finding.customer_shareable.is_(True))
    findings = session.scalars(stmt).all()
    return (
        {
            "findings": [
                {
                    "external_ref": f.external_ref,
                    "severity": f.severity,
                    "status": f.status,
                    "identified_date": f.identified_date.isoformat() if f.identified_date else None,
                    "target_remediation_date": (
                        f.target_remediation_date.isoformat()
                        if f.target_remediation_date
                        else None
                    ),
                    "remediated_date": f.remediated_date.isoformat() if f.remediated_date else None,
                    "remediation_summary": f.remediation_summary,
                }
                for f in findings
            ]
        },
        [],
    )


def execute_tool(
    session: Session,
    org: Organization,
    call: ToolCall,
    *,
    customer_facing: bool = True,
    top_k: int = 5,
) -> tuple[dict, list[CitedEvidence]]:
    """Run one read-only, org-scoped tool. Returns ``(result_for_model, new_cited_chunks)``;
    new chunks join the citeable pool the draft is later resolved against."""
    name = call.name
    args = call.arguments if isinstance(call.arguments, dict) else {}
    if name == SEARCH_EVIDENCE:
        return _search_evidence(
            session, org, args, customer_facing=customer_facing, top_k=top_k
        )
    if name == GET_POLICY:
        return _get_doc_chunks(
            session, org, args.get("id"), "policy", customer_facing=customer_facing
        )
    if name == GET_CONTROL:
        return _get_doc_chunks(
            session, org, args.get("id"), "control", customer_facing=customer_facing
        )
    if name == GET_FINDINGS:
        return _get_findings(
            session, org, args.get("document_id"), customer_facing=customer_facing
        )
    return {"error": f"unknown tool: {name}"}, []


def audit_view(call: ToolCall) -> dict:
    """Metadata-only view of a tool call for the audit trail (tool + query/id; never content,
    secrets, or PII). The query is the agent's own reformulation over our own corpus."""
    args = call.arguments if isinstance(call.arguments, dict) else {}
    view: dict = {"tool": call.name}
    if call.name == SEARCH_EVIDENCE:
        view["query"] = str(args.get("query") or "")[:200]
        types = _str_list(args.get("source_types"))
        if types:
            view["source_types"] = types
    elif call.name in (GET_POLICY, GET_CONTROL):
        view["id"] = str(args.get("id") or "")
    elif call.name == GET_FINDINGS:
        view["document_id"] = str(args.get("document_id") or "")
    return view


__all__ = [
    "TOOL_SPECS",
    "SEARCH_EVIDENCE",
    "GET_POLICY",
    "GET_CONTROL",
    "GET_FINDINGS",
    "execute_tool",
    "audit_view",
]
