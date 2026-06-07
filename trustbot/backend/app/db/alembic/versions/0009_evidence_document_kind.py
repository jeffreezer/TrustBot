"""evidence — document_kind (respond-mode provision, Milestone 1; §7 of the design)

Normalized artifact kind (soc2_report | iso_certificate | pci_aoc | pentest_report |
whitepaper | policy | document) so a document-request attaches the artifact the question
asks for — the SOC 2 / ISO / PCI attestation — rather than whatever the answer happened to
be grounded in. Backfilled from evidence_type for existing rows.

Revision ID: 0009_evidence_document_kind
Revises: 0008_answer_respond_attrs
Create Date: 2026-06-06
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_evidence_document_kind"
down_revision: str | None = "0008_answer_respond_attrs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# evidence_type -> document_kind backfill (matches the seed mapping).
_BACKFILL = {
    "soc2_report": "soc2_report",
    "iso_certificate": "iso_certificate",
    "pci_aoc": "pci_aoc",
    "pentest_summary": "pentest_report",
    "whitepaper": "whitepaper",
    "policy": "policy",
}


def upgrade() -> None:
    op.add_column("evidence", sa.Column("document_kind", sa.String(length=32), nullable=True))
    op.create_index("ix_evidence_document_kind", "evidence", ["document_kind"])
    evidence = sa.table(
        "evidence",
        sa.column("evidence_type", sa.String),
        sa.column("document_kind", sa.String),
    )
    for etype, kind in _BACKFILL.items():
        op.execute(
            evidence.update()
            .where(evidence.c.evidence_type == etype)
            .values(document_kind=kind)
        )
    # Anything still unset is a generic document.
    op.execute(
        evidence.update()
        .where(evidence.c.document_kind.is_(None))
        .values(document_kind="document")
    )


def downgrade() -> None:
    op.drop_index("ix_evidence_document_kind", table_name="evidence")
    op.drop_column("evidence", "document_kind")
