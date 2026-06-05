"""answers.review_status — persisted human-review decision (Phase 5)

The review workspace lets a human approve / edit / reject / request-evidence /
save-to-library each draft. ``review_status`` records the current decision (the full
history lives in ``answer_reviews`` + ``audit_log``), so the question list can show a
status at a glance and exports can carry approval state — nothing reads as "final"
unless a human approved it. Defaults to 'pending': a fresh draft is never approved.

Revision ID: 0004_answer_review_status
Revises: 0003_knowledge_chunk_fts_index
Create Date: 2026-06-05
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_answer_review_status"
down_revision: str | None = "0003_knowledge_chunk_fts_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "answers",
        sa.Column(
            "review_status",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
    )


def downgrade() -> None:
    op.drop_column("answers", "review_status")
