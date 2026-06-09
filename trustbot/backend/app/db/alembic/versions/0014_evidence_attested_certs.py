"""evidence — attested_certifications (evidence-derived cert grounding, 07 §3.3/§5)

Records which certifications an ingested attestation document actually attests, extracted from
its own text at ingestion (an ISO certificate/SoA → ISO 27001/27017/27018/27701; a SOC 2 report
→ SOC 2; a PCI AoC → PCI DSS). This is the evidence-first source of truth for "do we hold cert
X" — never a self-declared list — so removing the document removes the cert from "held". Defaults
to an empty list, so existing rows + non-attestation documents are unaffected.

Revision ID: 0014_evidence_attested_certs
Revises: 0013_answer_claims
Create Date: 2026-06-08
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0014_evidence_attested_certs"
down_revision: str | None = "0013_answer_claims"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "evidence",
        sa.Column(
            "attested_certifications",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("evidence", "attested_certifications")
