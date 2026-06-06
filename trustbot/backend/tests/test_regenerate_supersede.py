"""Regenerate supersedes prior drafts (soft) and preserves human-finalized answers.

DB-backed (Postgres-only types) — uses the shared ``pg_session`` fixture, which runs only
when ``TEST_DATABASE_URL`` is set and rolls everything back. ``stub_generate_answer`` makes
generation a plain draft, so no model/retrieval/network is needed.
"""
import uuid

from sqlalchemy import select

from app.db.models import Answer, Organization, Question, Questionnaire
from app.questionnaires import service


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


def test_regenerate_supersedes_and_keeps_one_live_per_question(pg_session, stub_generate_answer):
    org, qn, qids = _setup(pg_session)

    r0 = service.generate_drafts(pg_session, org=org, questionnaire_id=qn.id)
    assert r0["generated"] == 2
    live, sup = _live_superseded(pg_session, org, qn.id)
    assert len(live) == 2 and len(sup) == 0
    assert {a.question_id for a in live} == qids  # one live answer per question

    r1 = service.generate_drafts(pg_session, org=org, questionnaire_id=qn.id, regenerate=True)
    assert r1["generated"] == 2 and r1["preserved"] == 0
    live, sup = _live_superseded(pg_session, org, qn.id)
    assert len(live) == 2 and len(sup) == 2

    # regenerate twice (total) -> still exactly one live per question
    service.generate_drafts(pg_session, org=org, questionnaire_id=qn.id, regenerate=True)
    live, sup = _live_superseded(pg_session, org, qn.id)
    assert len(live) == 2 and len(sup) == 4
    assert {a.question_id for a in live} == qids


def test_approved_answer_is_preserved_across_regenerate(pg_session, stub_generate_answer):
    org, qn, _ = _setup(pg_session)
    service.generate_drafts(pg_session, org=org, questionnaire_id=qn.id)
    live, _ = _live_superseded(pg_session, org, qn.id)

    approved = live[0]
    service.review_answer(
        pg_session, org=org, answer_id=approved.id, action="approve", reviewer="reviewer@demo"
    )

    r = service.generate_drafts(pg_session, org=org, questionnaire_id=qn.id, regenerate=True)
    assert r["preserved"] == 1 and r["generated"] == 1

    live2, _ = _live_superseded(pg_session, org, qn.id)
    assert len(live2) == 2
    still_live = next(a for a in live2 if a.question_id == approved.question_id)
    assert still_live.id == approved.id  # same row — never replaced
    assert still_live.review_status == "approved"
    assert still_live.superseded_at is None
