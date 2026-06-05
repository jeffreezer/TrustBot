"""The two retrievers behind hybrid search: pgvector cosine + Postgres full-text.

Both share ``_base_stmt``, which applies the org scope and metadata filters, so the
tenancy/shareability guard can't be forgotten on one path. Keyword search uses
``plainto_tsquery`` with the query passed as a *bound parameter* — never string
concatenation — so untrusted question text can't inject SQL (CLAUDE.md).
"""
from __future__ import annotations

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from ..db.models import KnowledgeChunk
from .filters import RetrievalFilters

# Must match the index in migration 0003 or the planner can't use it.
_FTS_CONFIG = "english"


def _base_stmt(filters: RetrievalFilters) -> Select:
    stmt = select(KnowledgeChunk).where(KnowledgeChunk.org_id == filters.org_id)
    if filters.source_types:
        stmt = stmt.where(KnowledgeChunk.source_type.in_(list(filters.source_types)))
    if filters.confidentiality:
        stmt = stmt.where(
            KnowledgeChunk.meta["confidentiality"].astext.in_(
                list(filters.confidentiality)
            )
        )
    if filters.customer_shareable is not None:
        stmt = stmt.where(
            KnowledgeChunk.meta["customer_shareable"].as_boolean()
            == filters.customer_shareable
        )
    return stmt


def vector_search(
    session: Session,
    *,
    query_embedding: list[float],
    filters: RetrievalFilters,
    limit: int,
) -> list[KnowledgeChunk]:
    """Nearest chunks by pgvector cosine distance (ascending = most similar)."""
    stmt = (
        _base_stmt(filters)
        .where(KnowledgeChunk.embedding.is_not(None))
        .order_by(KnowledgeChunk.embedding.cosine_distance(query_embedding))
        .limit(limit)
    )
    return list(session.scalars(stmt))


def keyword_search(
    session: Session,
    *,
    query_text: str,
    filters: RetrievalFilters,
    limit: int,
) -> list[KnowledgeChunk]:
    """Best chunks by Postgres full-text rank for the query terms."""
    tsvector = func.to_tsvector(_FTS_CONFIG, KnowledgeChunk.chunk_text)
    tsquery = func.plainto_tsquery(_FTS_CONFIG, query_text)
    stmt = (
        _base_stmt(filters)
        .where(tsvector.op("@@")(tsquery))
        .order_by(func.ts_rank_cd(tsvector, tsquery).desc())
        .limit(limit)
    )
    return list(session.scalars(stmt))
