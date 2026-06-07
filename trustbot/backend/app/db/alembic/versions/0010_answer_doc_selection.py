"""answers — generic document-request selection (respond-mode; §8 of the design)

A document-request that names no specific artifact must not auto-attach (providing a document
is a disclosure decision). ``document_selection_required`` drives the review-pane picker;
``candidate_documents`` holds the org-scoped, customer_shareable, relevance-ranked candidates
the analyst chooses from. Both default empty/false, so existing answers are unaffected.

Revision ID: 0010_answer_doc_selection
Revises: 0009_evidence_document_kind
Create Date: 2026-06-07
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0010_answer_doc_selection"
down_revision: str | None = "0009_evidence_document_kind"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "answers",
        sa.Column(
            "document_selection_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "answers",
        sa.Column(
            "candidate_documents",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("answers", "candidate_documents")
    op.drop_column("answers", "document_selection_required")
