"""answers.superseded_at — soft-supersede prior drafts on regenerate (Phase 6 follow-up)

Regenerating a questionnaire used to insert new answer rows alongside the old ones,
piling up stale drafts. Instead of deleting (which would destroy history), regenerate now
stamps the prior *draft* with ``superseded_at``; approved/edited answers are never
superseded and ``audit_log`` is never touched — auditability over tidiness. NULL means the
live row; queries read only non-superseded answers.

Revision ID: 0005_answer_superseded_at
Revises: 0004_answer_review_status
Create Date: 2026-06-05
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_answer_superseded_at"
down_revision: str | None = "0004_answer_review_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "answers",
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("answers", "superseded_at")
