"""Seed the database with the synthetic Northwind AI demo company.

Loads, into one demo org:
  - company_profile  (raw markdown + a structured projection of canonical facts)
  - controls         (control_catalog.csv, preserving framework mappings / notes)
  - evidence         (each evidence file, uploaded through the storage adapter,
                      with a sha256 recorded for the audit trail)
  - evidence_control_links (framework-based associations)
  - approved_answer_library (Northwind's completed CAIQ + Security Questionnaire)

knowledge_chunks stay empty — parsing/chunking/embedding is Phase 2.

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


def _seed_dir() -> Path:
    path = Path(settings.seed_data_dir)
    if not path.is_dir():
        raise FileNotFoundError(f"seed data dir not found: {path} (set SEED_DATA_DIR)")
    return path


def _seed_company_profile(session: Session, org: Organization, seed_dir: Path) -> None:
    md_path = seed_dir / "company_profile.md"
    raw = md_path.read_text(encoding="utf-8")
    session.add(
        CompanyProfile(
            org_id=org.id,
            raw_markdown=raw,
            key_facts=KEY_FACTS,
            source_hash=_sha256(raw.encode("utf-8")),
        )
    )


def _seed_controls(session: Session, org: Organization, seed_dir: Path) -> int:
    csv_path = seed_dir / "control_catalog.csv"
    count = 0
    with csv_path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            code = (row.get("control_code") or "").strip()
            if not code:
                continue
            session.add(
                Control(
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
            )
            count += 1
    return count


def _seed_evidence(session: Session, org: Organization, seed_dir: Path) -> list[Evidence]:
    storage = get_storage()
    storage.ensure_bucket()  # no-op for local; provisions the bucket for S3/MinIO
    evidence_dir = seed_dir / "evidence"
    created: list[Evidence] = []
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
        created.append(ev)
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


def _seed_approved_answers(session: Session, org: Organization, seed_dir: Path) -> int:
    q_dir = seed_dir / "questionnaires"
    count = 0

    caiq_path = q_dir / "CAIQ_v4_Northwind_AI.xlsx"
    if caiq_path.is_file():
        for row in _read_questionnaire_rows(caiq_path):
            qid = row.get("Question ID", "").strip()
            if not qid:
                continue
            session.add(
                ApprovedAnswer(
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
            )
            count += 1

    secq_path = q_dir / "Security_Questionnaire_Northwind_AI.xlsx"
    if secq_path.is_file():
        for row in _read_questionnaire_rows(secq_path):
            qid = row.get("Question ID", "").strip()
            if not qid:
                continue
            session.add(
                ApprovedAnswer(
                    org_id=org.id,
                    source="Security Questionnaire",
                    question_external_id=qid,
                    domain=row.get("Domain") or None,
                    question_text=row.get("Question", ""),
                    answer_text=row.get("Response") or None,
                    answer_detail=row.get("Details / Additional Information") or None,
                    extra=None,
                )
            )
            count += 1
    return count


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

    _seed_company_profile(session, org, seed_dir)
    control_count = _seed_controls(session, org, seed_dir)
    evidence = _seed_evidence(session, org, seed_dir)
    link_count = _seed_evidence_links(session, org, evidence)
    approved_count = _seed_approved_answers(session, org, seed_dir)

    counts = {
        "controls": control_count,
        "evidence": len(evidence),
        "evidence_control_links": link_count,
        "approved_answers": approved_count,
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
