"""answers — per-part breakdown for decomposed compound answers (Phase 6; 06 §5)

A compound question is split into atomic sub-questions, each answered independently through
the full pipeline and recomposed. ``sub_answers`` stores that per-part structure (sub-question,
outcome, text, citations, review state) so the workspace shows which evidence supports which
part. Defaults to an empty list, so single-part answers are unaffected.

Revision ID: 0011_answer_sub_answers
Revises: 0010_answer_doc_selection
Create Date: 2026-06-07
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0011_answer_sub_answers"
down_revision: str | None = "0010_answer_doc_selection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "answers",
        sa.Column(
            "sub_answers",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("answers", "sub_answers")
