"""Seed the database with the synthetic Northwind AI demo company.

Loads, into one demo org:
  - company_profile  (raw markdown + a structured projection of canonical facts)
  - controls         (control_catalog.csv, preserving framework mappings / notes)
  - evidence         (each evidence file + each policy doc, uploaded through the
                      storage adapter, with a sha256 recorded for the audit trail)
  - evidence_control_links (framework-based associations + per-policy header links)
  - approved_answer_library (Northwind's completed CAIQ + Security Questionnaire)
  - knowledge_chunks  (company profile + evidence + policies + controls + approved
                       answers, parsed → chunked → embedded — Phases 2–3)

Idempotent: if the org already exists it is skipped, unless ``force=True`` (which
deletes and recreates it). Safe to run on every container start.

Security notes:
  - Seed files are treated strictly as DATA. Nothing here interprets file contents
    as instructions; that boundary is what the whole product is about.
  - Filenames are sanitized before becoming storage keys (path-traversal safe).
  - The audit_log entry records counts only — never secrets or raw content.
"""
from __future__ import annotations

import csv
import hashlib
import mimetypes
import re
from datetime import date
from pathlib import Path

import openpyxl
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import SessionLocal
from .db.models import (
    ApprovedAnswer,
    AuditLog,
    CompanyProfile,
    Control,
    Evidence,
    EvidenceControlLink,
    Organization,
)
from .ingestion import ingest_document, ingest_text
from .providers import get_embedding_provider
from .storage import get_storage, sanitize_filename

ORG_NAME = "Northwind AI, Inc."
ORG_SLUG = "northwind-ai"

# Curated structured projection of the canonical facts (company_profile.md / the
# answer-key README). The raw markdown remains the document of record.
KEY_FACTS = {
    "hosting": {"primary": "GCP", "secondary": "AWS", "regions": ["US", "EU"]},
    "encryption": {"at_rest": "AES-256", "in_transit": "TLS 1.2+", "cmek": "not_supported"},
    "identity": {"workforce_sso": "Okta", "mfa": "mandatory", "access_review": "quarterly"},
    "certifications": ["SOC 2 Type 2", "ISO 27001", "ISO 27017", "ISO 27018", "ISO 27701"],
    "pci": {"status": "compliant", "scope": "service_provider_billing_only"},
    "training_use": "not_by_default_opt_in_only",
    "subprocessors": ["GCP", "AWS", "Cloudflare", "Datadog", "Okta", "Stripe"],
    "soc2_period": "2025-01-01..2025-12-31",
}

# Evidence-file → (type, confidentiality, customer_shareable). All seed evidence is
# external-facing attestation material, hence shareable; the whitepaper is public.
EVIDENCE_META = {
    "SOC2_Type2_Report": ("soc2_report", "confidential", True),
    "Pentest_Executive_Summary": ("pentest_summary", "confidential", True),
    "PCI_DSS_AOC_ServiceProvider": ("pci_aoc", "confidential", True),
    "ISO27001_Certificate_and_SoA": ("iso_certificate", "confidential", True),
    "Security_Whitepaper": ("whitepaper", "public", True),
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


# Policy header parsing. Policies declare their own classification and the controls
# they support in a blockquote header (e.g. "> **Classification:** Public ...",
# "> **Related controls:** CC6.1, CC6.2, IAM (catalog)"). We derive confidentiality /
# shareability and the control links from those lines rather than a hardcoded table,
# so dropping a new policy file into the directory just works.
_HEADER_RE = {
    "classification": re.compile(r"\*{0,2}Classification:\*{0,2}\s*(.+)", re.IGNORECASE),
    "related": re.compile(r"\*{0,2}Related controls:\*{0,2}\s*(.+)", re.IGNORECASE),
}


def _classify_policy(classification: str) -> tuple[str, bool]:
    """Map a Classification header to (confidentiality, customer_shareable).

    Shareability is driven by the words in the header, never per-file rules:
      - "Public ..."                          -> public, shareable
      - "Internal — customer-shareable ..."   -> confidential, shareable
      - "Internal" (anything else)            -> internal, not shareable
    """
    value = classification.lower()
    if "public" in value:
        return "public", True
    if "customer-shareable" in value:
        return "confidential", True
    return "internal", False


def _parse_related_controls(value: str) -> list[str]:
    """Comma-separated control codes from a Related controls header.

    Trailing parentheticals like "IAM (catalog)" name a control *family*, not a code;
    we strip the "(...)" so the token becomes "IAM" and simply won't match a real
    control_code (the linker skips it). Order-preserving, de-duplicated.
    """
    codes: list[str] = []
    for token in value.split(","):
        token = re.sub(r"\s*\(.*?\)\s*$", "", token.strip()).strip()
        if token and token not in codes:
            codes.append(token)
    return codes


def _extract_policy_header(text: str) -> tuple[str, list[str]]:
    """Return (classification, related_control_codes) parsed from a policy's header."""
    classification = ""
    related: list[str] = []
    for line in text.splitlines():
        stripped = line.lstrip("> ").strip()
        if not classification and (m := _HEADER_RE["classification"].match(stripped)):
            classification = m.group(1).strip()
        if not related and (m := _HEADER_RE["related"].match(stripped)):
            related = _parse_related_controls(m.group(1))
        if classification and related:
            break
    return classification, related


def _extract_title(text: str, fallback: str) -> str:
    """The document's H1 (e.g. '# Northwind AI — Access Control Policy'), else fallback."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return fallback


def _seed_dir() -> Path:
    path = Path(settings.seed_data_dir)
    if not path.is_dir():
        raise FileNotFoundError(f"seed data dir not found: {path} (set SEED_DATA_DIR)")
    return path


def _seed_company_profile(
    session: Session, org: Organization, seed_dir: Path
) -> CompanyProfile:
    md_path = seed_dir / "company_profile.md"
    raw = md_path.read_text(encoding="utf-8")
    profile = CompanyProfile(
        org_id=org.id,
        raw_markdown=raw,
        key_facts=KEY_FACTS,
        source_hash=_sha256(raw.encode("utf-8")),
    )
    session.add(profile)
    session.flush()  # assign profile.id (used as the knowledge_chunk source_id)
    return profile


def _seed_controls(session: Session, org: Organization, seed_dir: Path) -> list[Control]:
    csv_path = seed_dir / "control_catalog.csv"
    created: list[Control] = []
    with csv_path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            code = (row.get("control_code") or "").strip()
            if not code:
                continue
            control = Control(
                org_id=org.id,
                control_code=code,
                domain=(row.get("domain") or "").strip() or None,
                title=(row.get("title") or "").strip(),
                implementation_statement=(row.get("implementation_statement") or "").strip() or None,
                owner=(row.get("owner") or "").strip() or None,
                status=(row.get("status") or "").strip() or None,
                framework_mappings=(row.get("framework_mappings") or "").strip() or None,
                last_reviewed=_parse_date(row.get("last_reviewed")),
                next_review=_parse_date(row.get("next_review")),
                confidence=(row.get("confidence") or "").strip() or None,
                notes=(row.get("notes") or "").strip() or None,
            )
            session.add(control)
            created.append(control)
    session.flush()  # assign control ids (used as knowledge_chunk source_ids)
    return created


def _seed_evidence(
    session: Session, org: Organization, seed_dir: Path
) -> list[tuple[Evidence, bytes]]:
    storage = get_storage()
    storage.ensure_bucket()  # no-op for local; provisions the bucket for S3/MinIO
    evidence_dir = seed_dir / "evidence"
    created: list[tuple[Evidence, bytes]] = []
    for file_path in sorted(evidence_dir.glob("*.md")):
        stem = file_path.stem
        data = file_path.read_bytes()
        etype, confidentiality, shareable = EVIDENCE_META.get(
            stem, ("document", "confidential", False)
        )
        ev = Evidence(
            org_id=org.id,
            title=stem.replace("_", " "),
            evidence_type=etype,
            original_filename=file_path.name,
            storage_path="",  # set after we know the evidence id
            content_type=mimetypes.guess_type(file_path.name)[0] or "text/markdown",
            file_hash=_sha256(data),
            file_size=len(data),
            owner="GRC",
            confidentiality=confidentiality,
            customer_shareable=shareable,
            status="active",
        )
        session.add(ev)
        session.flush()  # assign ev.id
        # Tenant-namespaced key: defense in depth inside the bucket.
        key = f"org/{org.id}/evidence/{ev.id}/{sanitize_filename(file_path.name)}"
        ev.storage_path = storage.put(key, data, content_type=ev.content_type)
        created.append((ev, data))
    return created


def _seed_evidence_links(
    session: Session, org: Organization, evidence: list[Evidence]
) -> int:
    """Associate evidence with controls by framework, plus an explicit pentest link."""
    controls = session.scalars(select(Control).where(Control.org_id == org.id)).all()
    by_code = {c.control_code: c for c in controls}
    links = 0

    def link(ev: Evidence, control: Control) -> None:
        nonlocal links
        session.add(
            EvidenceControlLink(org_id=org.id, evidence_id=ev.id, control_id=control.id)
        )
        links += 1

    for ev in evidence:
        if ev.evidence_type == "soc2_report":
            for c in controls:
                if c.framework_mappings and "SOC2" in c.framework_mappings:
                    link(ev, c)
        elif ev.evidence_type == "iso_certificate":
            for c in controls:
                if c.framework_mappings and "ISO 27001" in c.framework_mappings:
                    link(ev, c)
        elif ev.evidence_type == "pentest_summary":
            for code in ("PEN1.1", "CC7.1"):
                if code in by_code:
                    link(ev, by_code[code])
    return links


def _seed_policies(
    session: Session, org: Organization, seed_dir: Path
) -> list[tuple[Evidence, bytes, list[str]]]:
    """Load policies/*.md as Evidence rows (evidence_type='policy').

    Policies are governed documents that attest to controls, so they are stored as
    evidence (and become linkable via evidence_control_links). Their chunks are tagged
    source_type='policy' (see _seed_knowledge_chunks) so retrieval keeps them distinct.
    Classification / shareability is read from each file's header, not hardcoded.

    Returns (evidence, bytes, related_control_codes) so the caller can link + ingest.
    """
    policies_dir = seed_dir / "policies"
    created: list[tuple[Evidence, bytes, list[str]]] = []
    if not policies_dir.is_dir():
        return created

    storage = get_storage()
    storage.ensure_bucket()
    for file_path in sorted(policies_dir.glob("*.md")):
        data = file_path.read_bytes()
        text = data.decode("utf-8")
        classification, related_codes = _extract_policy_header(text)
        confidentiality, shareable = _classify_policy(classification)
        ev = Evidence(
            org_id=org.id,
            title=_extract_title(text, file_path.stem.replace("_", " ")),
            evidence_type="policy",
            original_filename=file_path.name,
            storage_path="",  # set after we know the evidence id
            content_type=mimetypes.guess_type(file_path.name)[0] or "text/markdown",
            file_hash=_sha256(data),
            file_size=len(data),
            owner="GRC",
            confidentiality=confidentiality,
            customer_shareable=shareable,
            status="active",
        )
        session.add(ev)
        session.flush()  # assign ev.id
        key = f"org/{org.id}/evidence/{ev.id}/{sanitize_filename(file_path.name)}"
        ev.storage_path = storage.put(key, data, content_type=ev.content_type)
        created.append((ev, data, related_codes))
    return created


def _seed_policy_links(
    session: Session,
    org: Organization,
    policies: list[tuple[Evidence, bytes, list[str]]],
) -> int:
    """Link each policy to the controls named in its Related controls header.

    Codes that don't match an existing control (e.g. family references like 'IAM')
    are skipped — the policy still ingests; it just isn't linked to a non-existent row.
    """
    controls = session.scalars(select(Control).where(Control.org_id == org.id)).all()
    by_code = {c.control_code: c for c in controls}
    links = 0
    for ev, _data, codes in policies:
        for code in codes:
            control = by_code.get(code)
            if control is None:
                continue
            session.add(
                EvidenceControlLink(
                    org_id=org.id, evidence_id=ev.id, control_id=control.id
                )
            )
            links += 1
    return links


def _control_text(control: Control) -> str:
    """Retrieval text for a control: its code/title plus the implementation statement."""
    parts = [f"{control.control_code} {control.title}".strip()]
    if control.implementation_statement:
        parts.append(control.implementation_statement)
    return "\n\n".join(p for p in parts if p.strip())


def _approved_answer_text(answer: ApprovedAnswer) -> str:
    """Retrieval text for an approved answer: the Q&A pair, so a new similar
    question matches on the question side and the answer is available for reuse."""
    parts: list[str] = []
    if answer.question_text and answer.question_text.strip():
        parts.append(f"Q: {answer.question_text.strip()}")
    if answer.answer_text and answer.answer_text.strip():
        parts.append(f"A: {answer.answer_text.strip()}")
    if answer.answer_detail and answer.answer_detail.strip():
        parts.append(answer.answer_detail.strip())
    return "\n\n".join(parts)


def _seed_knowledge_chunks(
    session: Session,
    org: Organization,
    profile: CompanyProfile,
    evidence: list[tuple[Evidence, bytes]],
    controls: list[Control],
    approved: list[ApprovedAnswer],
    policies: list[tuple[Evidence, bytes, list[str]]],
) -> int:
    """Parse → chunk → embed the full corpus into knowledge_chunks.

    Sources, each tagged with a distinct ``source_type`` so Phase 3 retrieval can
    search across (and weight) them and approved-answer reuse is distinguishable:
      - ``company_profile`` — the canonical company facts (internal)
      - ``evidence``        — uploaded attestation documents
      - ``policy``          — governed policy documents (header-declared shareability)
      - ``control``         — control implementation statements (internal)
      - ``approved_answer`` — prior approved Q&A, retrievable reuse *candidates*

    Confidentiality / shareability is copied onto each chunk's metadata so Phase 3
    retrieval and Phase 4 answer validation can filter without re-joining sources.
    """
    provider = get_embedding_provider()
    total = 0
    total += ingest_document(
        session,
        org_id=org.id,
        source_type="company_profile",
        source_id=profile.id,
        data=profile.raw_markdown.encode("utf-8"),
        content_type="text/markdown",
        filename="company_profile.md",
        meta={"title": "Company Profile", "confidentiality": "internal"},
        provider=provider,
    )
    for ev, data in evidence:
        total += ingest_document(
            session,
            org_id=org.id,
            source_type="evidence",
            source_id=ev.id,
            data=data,
            content_type=ev.content_type,
            filename=ev.original_filename,
            meta={
                "title": ev.title,
                "evidence_type": ev.evidence_type,
                "confidentiality": ev.confidentiality,
                "customer_shareable": ev.customer_shareable,
            },
            provider=provider,
        )
    for ev, data, _codes in policies:
        total += ingest_document(
            session,
            org_id=org.id,
            source_type="policy",
            source_id=ev.id,
            data=data,
            content_type=ev.content_type,
            filename=ev.original_filename,
            meta={
                "title": ev.title,
                "evidence_type": "policy",
                "confidentiality": ev.confidentiality,
                "customer_shareable": ev.customer_shareable,
            },
            provider=provider,
        )
    for control in controls:
        text = _control_text(control)
        if not text:
            continue
        # Control implementation statements are internal descriptions that inform a
        # drafted answer; the answer is what goes external, so they are not shareable.
        total += ingest_text(
            session,
            org_id=org.id,
            source_type="control",
            source_id=control.id,
            text=text,
            meta={
                "title": control.title,
                "control_code": control.control_code,
                "domain": control.domain,
                "confidentiality": "internal",
                "customer_shareable": False,
            },
            provider=provider,
        )
    for answer in approved:
        text = _approved_answer_text(answer)
        if not text:
            continue
        # Already-approved external questionnaire responses: shareable, but still
        # re-validated against current evidence before reuse (candidates, not bypass).
        total += ingest_text(
            session,
            org_id=org.id,
            source_type="approved_answer",
            source_id=answer.id,
            text=text,
            meta={
                "title": f"{answer.source} {answer.question_external_id}".strip(),
                "source": answer.source,
                "question_external_id": answer.question_external_id,
                "domain": answer.domain,
                "confidentiality": "confidential",
                "customer_shareable": True,
            },
            provider=provider,
        )
    return total


def _read_questionnaire_rows(path: Path) -> list[dict[str, str]]:
    """Find the data sheet (one with a 'Question ID' header) and yield header-keyed rows."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        for ws in wb.worksheets:
            rows = list(ws.iter_rows(values_only=True))
            header_idx = next(
                (
                    i
                    for i, r in enumerate(rows)
                    if r and any(str(c).strip().lower() == "question id" for c in r if c)
                ),
                None,
            )
            if header_idx is None:
                continue
            headers = [str(c).strip() if c is not None else "" for c in rows[header_idx]]
            out: list[dict[str, str]] = []
            for r in rows[header_idx + 1 :]:
                if not r or all(c is None or str(c).strip() == "" for c in r):
                    continue
                record = {
                    headers[i]: ("" if c is None else str(c).strip())
                    for i, c in enumerate(r)
                    if i < len(headers) and headers[i]
                }
                out.append(record)
            return out
        return []
    finally:
        wb.close()


def _seed_approved_answers(
    session: Session, org: Organization, seed_dir: Path
) -> list[ApprovedAnswer]:
    q_dir = seed_dir / "questionnaires"
    created: list[ApprovedAnswer] = []

    caiq_path = q_dir / "CAIQ_v4_Northwind_AI.xlsx"
    if caiq_path.is_file():
        for row in _read_questionnaire_rows(caiq_path):
            qid = row.get("Question ID", "").strip()
            if not qid:
                continue
            answer = ApprovedAnswer(
                org_id=org.id,
                source="CAIQ v4.0.3",
                question_external_id=qid,
                domain=qid.split("-", 1)[0] if "-" in qid else None,
                question_text=row.get("Question", ""),
                answer_text=row.get("CSP CAIQ Answer") or None,
                answer_detail=row.get("CSP Implementation Description") or None,
                extra={
                    "ssrm_ownership": row.get("SSRM Control Ownership") or None,
                    "csc_responsibilities": row.get("CSC Responsibilities") or None,
                },
            )
            session.add(answer)
            created.append(answer)

    secq_path = q_dir / "Security_Questionnaire_Northwind_AI.xlsx"
    if secq_path.is_file():
        for row in _read_questionnaire_rows(secq_path):
            qid = row.get("Question ID", "").strip()
            if not qid:
                continue
            answer = ApprovedAnswer(
                org_id=org.id,
                source="Security Questionnaire",
                question_external_id=qid,
                domain=row.get("Domain") or None,
                question_text=row.get("Question", ""),
                answer_text=row.get("Response") or None,
                answer_detail=row.get("Details / Additional Information") or None,
                extra=None,
            )
            session.add(answer)
            created.append(answer)
    session.flush()  # assign answer ids (used as knowledge_chunk source_ids)
    return created


def seed(session: Session, *, force: bool = False) -> dict:
    existing = session.scalar(select(Organization).where(Organization.slug == ORG_SLUG))
    if existing is not None:
        if not force:
            return {"status": "skipped", "reason": "already seeded", "org_id": str(existing.id)}
        session.delete(existing)  # cascades to all org-owned rows
        session.flush()

    seed_dir = _seed_dir()
    org = Organization(name=ORG_NAME, slug=ORG_SLUG)
    session.add(org)
    session.flush()

    profile = _seed_company_profile(session, org, seed_dir)
    controls = _seed_controls(session, org, seed_dir)
    evidence = _seed_evidence(session, org, seed_dir)
    policies = _seed_policies(session, org, seed_dir)
    link_count = _seed_evidence_links(session, org, [ev for ev, _ in evidence])
    link_count += _seed_policy_links(session, org, policies)
    approved = _seed_approved_answers(session, org, seed_dir)
    chunk_count = _seed_knowledge_chunks(
        session, org, profile, evidence, controls, approved, policies
    )

    counts = {
        "controls": len(controls),
        "evidence": len(evidence),
        "policies": len(policies),
        "evidence_control_links": link_count,
        "approved_answers": len(approved),
        "knowledge_chunks": chunk_count,
    }
    session.add(
        AuditLog(
            org_id=org.id,
            actor="system:seed",
            action="seed.run",
            target_type="organization",
            target_id=org.id,
            payload=counts,  # counts only — no secrets, no raw content
        )
    )
    session.commit()
    return {"status": "seeded", "org_id": str(org.id), **counts}


def main() -> None:
    import json
    import os

    force = os.getenv("RESEED", "").lower() in ("1", "true", "yes")
    with SessionLocal() as session:
        result = seed(session, force=force)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
