"""Fixed retrieve-then-answer pipeline (Phase 3 retrieval half).

A deliberately *fixed* pipeline — embed the query, run both retrievers, fuse, rerank,
return the top few — before any agentic loop (CLAUDE.md: "fixed retrieve-then-answer
pipeline before the agentic loop"). Phase 4 consumes ``RetrievedChunk`` to draft and
validate answers.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..config import settings
from ..db.models import KnowledgeChunk
from ..providers import (
    EmbeddingProvider,
    RerankProvider,
    get_embedding_provider,
    get_rerank_provider,
)
from .filters import RetrievalFilters
from .fusion import reciprocal_rank_fusion
from .search import keyword_search, vector_search


@dataclass
class RetrievedChunk:
    chunk_id: uuid.UUID
    source_type: str
    source_id: uuid.UUID | None
    chunk_text: str
    meta: dict
    fusion_score: float
    rerank_score: float


def retrieve(
    session: Session,
    *,
    query: str,
    filters: RetrievalFilters,
    embedder: EmbeddingProvider | None = None,
    reranker: RerankProvider | None = None,
    candidate_k: int | None = None,
    top_k: int | None = None,
) -> list[RetrievedChunk]:
    """Hybrid retrieve: vector + keyword → RRF fusion → rerank → top_k."""
    query = query.strip()
    if not query:
        return []

    embedder = embedder or get_embedding_provider()
    reranker = reranker or get_rerank_provider()
    candidate_k = settings.retrieval_candidate_k if candidate_k is None else candidate_k
    top_k = settings.retrieval_top_k if top_k is None else top_k

    query_embedding = embedder.embed_query(query)
    vector_hits = vector_search(
        session, query_embedding=query_embedding, filters=filters, limit=candidate_k
    )
    keyword_hits = keyword_search(
        session, query_text=query, filters=filters, limit=candidate_k
    )

    by_id: dict[uuid.UUID, KnowledgeChunk] = {c.id: c for c in vector_hits}
    for c in keyword_hits:
        by_id.setdefault(c.id, c)

    fused = reciprocal_rank_fusion(
        [[c.id for c in vector_hits], [c.id for c in keyword_hits]]
    )
    if not fused:
        return []
    fusion_score = dict(fused)

    chunks = [by_id[cid] for cid, _ in fused]
    rerank_scores = reranker.score(query, [c.chunk_text for c in chunks])

    # Sort by reranker, breaking ties by fusion score so a passthrough reranker
    # (equal scores) preserves the fused order exactly.
    order = sorted(
        range(len(chunks)),
        key=lambda i: (rerank_scores[i], fusion_score[chunks[i].id]),
        reverse=True,
    )

    return [
        RetrievedChunk(
            chunk_id=chunks[i].id,
            source_type=chunks[i].source_type,
            source_id=chunks[i].source_id,
            chunk_text=chunks[i].chunk_text,
            meta=chunks[i].meta,
            fusion_score=fusion_score[chunks[i].id],
            rerank_score=rerank_scores[i],
        )
        for i in order[:top_k]
    ]
