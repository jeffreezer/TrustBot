"""Read-only, org-scoped agent tools (Phase 6, 06 §4) — DB-backed.

Pins the security contract: every tool enforces org_id server-side (the model never supplies
it), so a cross-org id finds nothing (deny, no leak); customer-facing calls return only
customer_shareable content; and the audit view carries metadata only.
"""
import uuid

from app.answers.agent_tools import (
    GET_CONTROL,
    GET_FINDINGS,
    GET_POLICY,
    SEARCH_EVIDENCE,
    audit_view,
    execute_tool,
)
from app.db.models import (
    Control,
    Evidence,
    Finding,
    KnowledgeChunk,
    Organization,
)
from app.providers import ToolCall


def _org(session, name="Tools Org") -> Organization:
    org = Organization(name=name, slug=f"tools-{uuid.uuid4().hex[:8]}")
    session.add(org)
    session.flush()
    return org


def _policy_with_chunk(session, org, *, title, shareable=True) -> Evidence:
    ev = Evidence(
        org_id=org.id,
        title=title,
        evidence_type="policy",
        document_kind="policy",
        original_filename=f"{title}.md",
        storage_path="x",
        file_hash="h",
        confidentiality="confidential",
        customer_shareable=shareable,
        status="active",
    )
    session.add(ev)
    session.flush()
    session.add(
        KnowledgeChunk(
            org_id=org.id,
            source_type="policy",
            source_id=ev.id,
            chunk_index=0,
            chunk_text=f"{title}: background checks are performed prior to start.",
            meta={"title": title, "customer_shareable": shareable, "confidentiality": "confidential"},
        )
    )
    session.flush()
    return ev


def _call(name, **args) -> ToolCall:
    return ToolCall(id="c1", name=name, arguments=args)


def test_get_policy_returns_org_chunks(pg_session):
    org = _org(pg_session)
    ev = _policy_with_chunk(pg_session, org, title="HR Security Policy")
    result, cited = execute_tool(pg_session, org, _call(GET_POLICY, id=str(ev.id)))
    assert result["found"] is True
    assert result["title"] == "HR Security Policy"
    assert cited and cited[0].source_id == str(ev.id)


def test_get_policy_cross_org_denied_without_leak(pg_session):
    org_a = _org(pg_session, "A")
    org_b = _org(pg_session, "B")
    ev_b = _policy_with_chunk(pg_session, org_b, title="B's Policy")
    # Scoped to org A, asking for org B's policy id → indistinguishable from unknown.
    result, cited = execute_tool(pg_session, org_a, _call(GET_POLICY, id=str(ev_b.id)))
    assert result == {"found": False}
    assert cited == []


def test_get_policy_non_shareable_hidden_when_customer_facing(pg_session):
    org = _org(pg_session)
    ev = _policy_with_chunk(pg_session, org, title="Internal Only", shareable=False)
    # Customer-facing (default): internal-only policy must not surface.
    result, _c = execute_tool(pg_session, org, _call(GET_POLICY, id=str(ev.id)))
    assert result == {"found": False}
    # Internal answer path may see it.
    result2, cited2 = execute_tool(
        pg_session, org, _call(GET_POLICY, id=str(ev.id)), customer_facing=False
    )
    assert result2["found"] is True and cited2


def test_get_control_is_org_scoped(pg_session):
    org = _org(pg_session)
    ctrl = Control(
        org_id=org.id,
        control_code="HR1.1",
        title="Background checks",
        domain="HR",
    )
    pg_session.add(ctrl)
    pg_session.flush()
    pg_session.add(
        KnowledgeChunk(
            org_id=org.id,
            source_type="control",
            source_id=ctrl.id,
            chunk_index=0,
            chunk_text="HR1.1 Background checks are performed where permitted by law.",
            meta={"title": "HR1.1 Background checks", "customer_shareable": True},
        )
    )
    pg_session.flush()
    result, cited = execute_tool(pg_session, org, _call(GET_CONTROL, id=str(ctrl.id)))
    assert result["found"] is True
    assert cited and cited[0].source_type == "control"
    # Unknown id → deny.
    miss, _c = execute_tool(pg_session, org, _call(GET_CONTROL, id=str(uuid.uuid4())))
    assert miss == {"found": False}


def test_get_findings_is_org_scoped_and_shareable(pg_session):
    org = _org(pg_session)
    pentest = Evidence(
        org_id=org.id,
        title="Pentest",
        evidence_type="pentest_summary",
        document_kind="pentest_report",
        original_filename="p.md",
        storage_path="x",
        file_hash="h",
        confidentiality="confidential",
        customer_shareable=True,
        status="active",
    )
    pg_session.add(pentest)
    pg_session.flush()
    pg_session.add(
        Finding(
            org_id=org.id,
            source_document_id=pentest.id,
            source_type="pentest",
            external_ref="H-01",
            title="Open finding",
            status="in_progress",
            target_remediation_date=None,
            customer_shareable=True,
        )
    )
    pg_session.flush()
    result, cited = execute_tool(
        pg_session, org, _call(GET_FINDINGS, document_id=str(pentest.id))
    )
    assert [f["external_ref"] for f in result["findings"]] == ["H-01"]
    assert cited == []  # findings inform; they are not citeable evidence chunks
    # Cross-org document id → empty (deny).
    other = _org(pg_session, "Other")
    miss, _c = execute_tool(pg_session, other, _call(GET_FINDINGS, document_id=str(pentest.id)))
    assert miss["findings"] == []


def test_invalid_id_is_rejected_not_executed(pg_session):
    org = _org(pg_session)
    result, cited = execute_tool(pg_session, org, _call(GET_POLICY, id="not-a-uuid"))
    assert "error" in result and cited == []


def test_unknown_tool_is_rejected(pg_session):
    org = _org(pg_session)
    result, cited = execute_tool(pg_session, org, _call("delete_everything", id="x"))
    assert "error" in result and cited == []


def test_audit_view_is_metadata_only():
    view = audit_view(_call(SEARCH_EVIDENCE, query="background checks", source_types=["policy"]))
    assert view == {"tool": "search_evidence", "query": "background checks", "source_types": ["policy"]}
    assert "results" not in view  # never the retrieved content
