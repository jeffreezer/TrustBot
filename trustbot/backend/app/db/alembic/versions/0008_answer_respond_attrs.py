"""answers — respond-mode attributes (Milestone 1; §5 of the design)

Adds the respond-mode answer attributes alongside the parked review-mode columns: ``mode``
(which posture produced the answer), ``requires_document`` + ``provided_documents`` (the
document-provision answer + its org-scoped download targets), and ``remediation_required`` +
``finding_refs`` (the remediation block rendered from the findings register). The legacy
``exceptions``/``outcome`` columns are kept — review mode forks back onto them in M2.

Revision ID: 0008_answer_respond_attrs
Revises: 0007_findings_register
Create Date: 2026-06-06
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0008_answer_respond_attrs"
down_revision: str | None = "0007_findings_register"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "answers",
        sa.Column("mode", sa.String(length=16), nullable=False, server_default="respond"),
    )
    op.add_column(
        "answers",
        sa.Column(
            "requires_document", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "answers",
        sa.Column(
            "provided_documents",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "answers",
        sa.Column(
            "remediation_required", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "answers",
        sa.Column(
            "finding_refs",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("answers", "finding_refs")
    op.drop_column("answers", "remediation_required")
    op.drop_column("answers", "provided_documents")
    op.drop_column("answers", "requires_document")
    op.drop_column("answers", "mode")
