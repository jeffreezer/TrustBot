"""Background generation-job worker + job route — DB-backed (skips without TEST_DATABASE_URL).

Covers the worker's progress increments, failure path, and restart-orphan cleanup; the
batch cap and concurrency guard at job creation; and the org-scoping of GET /jobs/{id}
(cross-org → 404). ``generate_answer`` is stubbed, so no model/network is used.
"""
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.config import settings
from app.db.models import Answer, GenerationJob, Organization, Question, Questionnaire
from app.questionnaires import jobs, service
from app.review_routes import get_job


def _setup(session, *, n: int = 2) -> tuple[Organization, Questionnaire]:
    org = Organization(name="Jobs Test", slug=f"test-jobs-{uuid.uuid4().hex[:8]}")
    session.add(org)
    session.flush()
    qn = Questionnaire(org_id=org.id, title="T", status="uploaded")
    session.add(qn)
    session.flush()
    for i in range(n):
        session.add(
            Question(org_id=org.id, questionnaire_id=qn.id, text=f"Q{i}?", row_index=i)
        )
    session.flush()
    return org, qn


def _add_job(session, org, qn, **kw) -> GenerationJob:
    kw.setdefault("status", "pending")
    kw.setdefault("total", 0)
    kw.setdefault("completed", 0)
    job = GenerationJob(org_id=org.id, questionnaire_id=qn.id, **kw)
    session.add(job)
    session.flush()
    return job


def test_on_progress_increments_once_per_question(pg_session, stub_generate_answer):
    org, qn = _setup(pg_session, n=3)
    ticks: list[tuple[int, int]] = []
    service.generate_drafts(
        pg_session, org=org, questionnaire_id=qn.id, on_progress=lambda c, t: ticks.append((c, t))
    )
    assert ticks == [(1, 3), (2, 3), (3, 3)]


def test_execute_job_runs_to_done(pg_session, stub_generate_answer):
    org, qn = _setup(pg_session, n=3)
    job = _add_job(pg_session, org, qn, total=3)
    jobs._execute_job(pg_session, job=job, regenerate=False)
    pg_session.refresh(job)
    assert job.status == "done"
    assert job.completed == 3
    assert job.error is None
    live = pg_session.scalars(
        select(Answer)
        .join(Question, Answer.question_id == Question.id)
        .where(Question.questionnaire_id == qn.id, Answer.superseded_at.is_(None))
    ).all()
    assert len(live) == 3


def test_execute_job_marks_failed_with_generic_error(pg_session, monkeypatch):
    org, qn = _setup(pg_session, n=1)
    job = _add_job(pg_session, org, qn, total=1)

    def _boom(*_a, **_k):
        raise RuntimeError("db exploded — secret_value_xyz")

    monkeypatch.setattr(jobs, "generate_drafts", _boom)
    jobs._execute_job(pg_session, job=job, regenerate=False)
    pg_session.refresh(job)
    assert job.status == "failed"
    assert job.error == "generation failed"  # generic — no leaked detail
    assert "secret" not in (job.error or "")


def test_fail_orphaned_jobs(pg_session):
    org, qn = _setup(pg_session, n=1)
    running = _add_job(pg_session, org, qn, status="running", total=1)
    pending = _add_job(pg_session, org, qn, status="pending", total=1)
    done = _add_job(pg_session, org, qn, status="done", total=1, completed=1)

    n = jobs.fail_orphaned_jobs(pg_session)
    pg_session.flush()
    assert n == 2
    for j in (running, pending, done):
        pg_session.refresh(j)
    assert running.status == "failed" and running.error == "interrupted by restart"
    assert pending.status == "failed"
    assert done.status == "done"  # terminal job left untouched


def test_batch_cap_rejects_over_limit(pg_session, monkeypatch):
    monkeypatch.setattr(settings, "max_generation_batch", 2)
    org, qn = _setup(pg_session, n=3)
    with pytest.raises(jobs.BatchTooLargeError):
        jobs.create_generation_job(pg_session, org=org, questionnaire_id=qn.id)


def test_concurrent_job_rejected(pg_session):
    org, qn = _setup(pg_session, n=1)
    jobs.create_generation_job(pg_session, org=org, questionnaire_id=qn.id)
    pg_session.flush()
    with pytest.raises(jobs.ConcurrentJobError):
        jobs.create_generation_job(pg_session, org=org, questionnaire_id=qn.id)


def test_get_job_is_org_scoped(pg_session):
    org_a = Organization(name="A", slug=f"a-{uuid.uuid4().hex[:8]}")
    org_b = Organization(name="B", slug=f"b-{uuid.uuid4().hex[:8]}")
    pg_session.add_all([org_a, org_b])
    pg_session.flush()
    qn_b = Questionnaire(org_id=org_b.id, title="B", status="uploaded")
    pg_session.add(qn_b)
    pg_session.flush()
    job_b = _add_job(pg_session, org_b, qn_b, status="running", total=5, completed=2)

    # Call the route handler directly (no HTTP client dep). org A cannot see org B's job —
    # default deny, 404 (no existence disclosure).
    with pytest.raises(HTTPException) as exc:
        get_job(str(job_b.id), session=pg_session, org=org_a)
    assert exc.value.status_code == 404

    # org B sees its own job.
    body = get_job(str(job_b.id), session=pg_session, org=org_b)
    assert body["status"] == "running" and body["total"] == 5 and body["completed"] == 2
