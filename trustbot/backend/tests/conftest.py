"""Shared test fixtures.

``pg_session`` is a DB-backed session for the integration tests that exercise the review
service / job worker (the models use Postgres-only types, so SQLite can't stand in). It
runs only when ``TEST_DATABASE_URL`` points at a reachable Postgres (e.g. the compose
stack) and is skipped otherwise, so the offline suite stays green. Everything happens
inside an outer transaction that is rolled back at the end — and a SAVEPOINT is kept
restarted under the code's own ``commit()`` calls — so the target database is never
mutated.
"""
import os

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session


@pytest.fixture
def pg_session():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("set TEST_DATABASE_URL (e.g. the compose Postgres) to run DB tests")
    engine = create_engine(url, future=True)
    try:
        connection = engine.connect()
    except Exception as exc:  # noqa: BLE001 - any connect failure => skip, not fail
        engine.dispose()
        pytest.skip(f"TEST_DATABASE_URL not reachable: {type(exc).__name__}")

    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False, future=True)
    nested = connection.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def _restart_savepoint(_session, _transaction):
        nonlocal nested
        if not nested.is_active:
            nested = connection.begin_nested()

    try:
        yield session
    finally:
        event.remove(session, "after_transaction_end", _restart_savepoint)
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


@pytest.fixture
def stub_generate_answer(monkeypatch):
    """Replace the LLM/retrieval pipeline with a plain draft — no model, network, or
    embeddings — so worker/service tests run fast and offline of any provider."""
    from app.answers.schema import ConfidenceBand, GeneratedAnswer, Outcome
    from app.questionnaires import service

    def _fake(_session, *, org, question, top_k=None, generator=None):
        return GeneratedAnswer(
            question=question,
            outcome=Outcome.SUPPORTED_YES,
            short_answer="draft",
            answer="draft answer",
            claim="claim",
            confidence=0.8,
            confidence_band=ConfidenceBand.HIGH,
            needs_human_review=False,
            freshness_status="current",
            generated_by="phase4:test",
        )

    monkeypatch.setattr(service, "generate_answer", _fake)
    return _fake
