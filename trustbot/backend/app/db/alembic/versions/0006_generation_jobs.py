"""generation_jobs — durable background draft-generation jobs (Phase 6 async)

A pollable job row tracks an async generation run so the UI can show N/total progress and
survive navigation/refresh. ``id`` is a random UUID (non-guessable); reads are still
org-scoped. ``error`` carries a generic message only.

Revision ID: 0006_generation_jobs
Revises: 0005_answer_superseded_at
Create Date: 2026-06-05
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0006_generation_jobs"
down_revision: str | None = "0005_answer_superseded_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "generation_jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organization.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "questionnaire_id",
            UUID(as_uuid=True),
            sa.ForeignKey("questionnaires.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_generation_jobs_org_id", "generation_jobs", ["org_id"])
    op.create_index(
        "ix_generation_jobs_questionnaire_id", "generation_jobs", ["questionnaire_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_generation_jobs_questionnaire_id", table_name="generation_jobs")
    op.drop_index("ix_generation_jobs_org_id", table_name="generation_jobs")
    op.drop_table("generation_jobs")
