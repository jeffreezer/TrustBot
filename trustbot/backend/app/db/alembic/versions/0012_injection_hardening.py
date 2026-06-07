"""injection hardening — flag + quarantine columns (Phase 8)

Records prompt-injection detection at the boundary. answers.injection_flagged marks an answer
whose question or cited evidence screened as injection-like (neutralized + flagged — respond
mode). evidence.injection_flagged + injection_snippet record a detection on an ingested
document; under the review-mode quarantine policy the document's status becomes 'quarantined'
and its chunks are excluded from retrieval until a human releases it. All default to inert so
existing rows are unaffected.

Revision ID: 0012_injection_hardening
Revises: 0011_answer_sub_answers
Create Date: 2026-06-07
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_injection_hardening"
down_revision: str | None = "0011_answer_sub_answers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "answers",
        sa.Column(
            "injection_flagged", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "evidence",
        sa.Column(
            "injection_flagged", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "evidence",
        sa.Column("injection_snippet", sa.String(length=512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("evidence", "injection_snippet")
    op.drop_column("evidence", "injection_flagged")
    op.drop_column("answers", "injection_flagged")
