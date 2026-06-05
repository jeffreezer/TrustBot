"""knowledge_chunks full-text search index

Phase 3 hybrid retrieval keyword-searches chunk text with Postgres' built-in
full-text search (no extra service). A GIN index on the same
``to_tsvector('english', chunk_text)`` expression the query uses keeps that search
fast as the corpus grows. The 'english' config must match the query side exactly or
the planner can't use the index.

Revision ID: 0003_knowledge_chunk_fts_index
Revises: 0002_baseline_schema
Create Date: 2026-06-05
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0003_knowledge_chunk_fts_index"
down_revision: str | None = "0002_baseline_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_fts "
        "ON knowledge_chunks "
        "USING GIN (to_tsvector('english', chunk_text))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_knowledge_chunks_fts")
