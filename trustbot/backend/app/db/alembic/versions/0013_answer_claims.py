"""answers — structured claims backing an answer (07 claim/attestation model, Phase 1)

The generator declares structured claims and the certification-question outcome + the cert
overclaim validator derive from them, not from the prose (07 §3) — which fixes the FedRAMP
false-positive (a grounded negative no longer trips a keyword scan) structurally. Phase 1
stores certification claims only: [{subject, claim_type, status, basis[], confidence,
customer_shareable}]. Defaults to an empty list, so existing rows + non-certification answers
are unaffected.

Revision ID: 0013_answer_claims
Revises: 0012_injection_hardening
Create Date: 2026-06-07
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0013_answer_claims"
down_revision: str | None = "0012_injection_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "answers",
        sa.Column(
            "claims",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("answers", "claims")
