"""findings — remediation register (respond-mode, Milestone 1; §9 of the design)

Structured findings from a pentest / SOC 2 exception / internal audit / vuln scan, so the
document-provision answer can render current remediation status + closure dates rather than
the drafter inventing them. ``org_id`` is enforced on every query (default deny); severity
is stored verbatim; the customer-facing render shows shareable fields only.

Revision ID: 0007_findings_register
Revises: 0006_generation_jobs
Create Date: 2026-06-06
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0007_findings_register"
down_revision: str | None = "0006_generation_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "findings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organization.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_document_id",
            UUID(as_uuid=True),
            sa.ForeignKey("evidence.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("external_ref", sa.String(length=64), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("severity", sa.String(length=64), nullable=True),
        sa.Column("severity_rank", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="open"),
        sa.Column("identified_date", sa.Date(), nullable=True),
        sa.Column("target_remediation_date", sa.Date(), nullable=True),
        sa.Column("remediated_date", sa.Date(), nullable=True),
        sa.Column("remediation_summary", sa.Text(), nullable=True),
        sa.Column("owner", sa.String(length=128), nullable=True),
        sa.Column(
            "customer_shareable", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "confidentiality", sa.String(length=32), nullable=False, server_default="internal"
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_findings_org_id", "findings", ["org_id"])
    op.create_index(
        "ix_findings_source_document_id", "findings", ["source_document_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_findings_source_document_id", table_name="findings")
    op.drop_index("ix_findings_org_id", table_name="findings")
    op.drop_table("findings")
