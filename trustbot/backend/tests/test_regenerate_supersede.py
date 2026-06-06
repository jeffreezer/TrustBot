"""Regenerate supersedes prior drafts (soft) and preserves human-finalized answers.

DB-backed: the models use Postgres-only types (JSONB/UUID), so this runs only when
``TEST_DATABASE_URL`` points at a reachable Postgres (e.g. the compose stack) and is
skipped otherwise — the offline suite stays green. Everything runs inside a transaction
that is rolled back, so the target DB is left untouched. ``generate_answer`` is stubbed,
so no embedding model, retrieval, or network is needed.
"""
import os
import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.answers.schema import ConfidenceBand, GeneratedAnswer, Outcome
from app.db.models import Answer, Organization, Question, Questionnaire
from app.questionnaires import service


@pytest.fixture
def pg(monkeypatch):
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("set TEST_DATABASE_URL to run the DB-backed supersede test")
    engine = create_engine(url, future=True)
    try:
        conn = engine.connect()
    except Exception as exc:  # noqa: BLE001 - any connect failure => skip, not fail
        pytest.skip(f"TEST_DATABASE_URL not reachable: {type(exc).__name__}")
    txn = conn.begin()
    session = Session(bind=conn, future=True)

    def _fake_generate_answer(_session, *, org, question, top_k=None, generator=None):
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

    monkeypatch.setattr(service, "generate_answer", _fake_generate_answer)
    try:
        yield session
    finally:
        session.close()
        txn.rollback()
        conn.close()
        engine.dispose()


def _setup(session) -> tuple[Organization, Questionnaire, set]:
    org = Organization(name="Supersede Test", slug=f"test-supersede-{uuid.uuid4().hex[:8]}")
    session.add(org)
    session.flush()
    qn = Questionnaire(org_id=org.id, title="T", status="uploaded")
    session.add(qn)
    session.flush()
    for i in range(2):
        session.add(
            Question(org_id=org.id, questionnaire_id=qn.id, text=f"Q{i}?", row_index=i)
        )
    session.flush()
    qids = {
        q.id
        for q in session.scalars(
            select(Question).where(Question.questionnaire_id == qn.id)
        )
    }
    return org, qn, qids


def _live_superseded(session, org, qn_id):
    rows = session.scalars(
        select(Answer)
        .join(Question, Answer.question_id == Question.id)
        .where(Question.questionnaire_id == qn_id, Answer.org_id == org.id)
    ).all()
    live = [a for a in rows if a.superseded_at is None]
    superseded = [a for a in rows if a.superseded_at is not None]
    return live, superseded


def test_regenerate_supersedes_and_keeps_one_live_per_question(pg):
    org, qn, qids = _setup(pg)

    r0 = service.generate_drafts(pg, org=org, questionnaire_id=qn.id)
    assert r0["generated"] == 2
    live, sup = _live_superseded(pg, org, qn.id)
    assert len(live) == 2 and len(sup) == 0
    assert {a.question_id for a in live} == qids  # one live answer per question

    # regenerate once -> prior drafts superseded, fresh drafts live
    r1 = service.generate_drafts(pg, org=org, questionnaire_id=qn.id, regenerate=True)
    assert r1["generated"] == 2 and r1["preserved"] == 0
    live, sup = _live_superseded(pg, org, qn.id)
    assert len(live) == 2 and len(sup) == 2

    # regenerate twice (total) -> still exactly one live per question
    service.generate_drafts(pg, org=org, questionnaire_id=qn.id, regenerate=True)
    live, sup = _live_superseded(pg, org, qn.id)
    assert len(live) == 2 and len(sup) == 4
    assert {a.question_id for a in live} == qids


def test_approved_answer_is_preserved_across_regenerate(pg):
    org, qn, _ = _setup(pg)
    service.generate_drafts(pg, org=org, questionnaire_id=qn.id)
    live, _ = _live_superseded(pg, org, qn.id)

    approved = live[0]
    service.review_answer(
        pg, org=org, answer_id=approved.id, action="approve", reviewer="reviewer@demo"
    )

    r = service.generate_drafts(pg, org=org, questionnaire_id=qn.id, regenerate=True)
    # one question preserved (the approved one), the other regenerated
    assert r["preserved"] == 1 and r["generated"] == 1

    live2, _ = _live_superseded(pg, org, qn.id)
    assert len(live2) == 2
    still_live = next(a for a in live2 if a.question_id == approved.question_id)
    assert still_live.id == approved.id  # same row — never replaced
    assert still_live.review_status == "approved"
    assert still_live.superseded_at is None
