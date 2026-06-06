"""Route-level tests for the generation-job endpoints, through the real FastAPI stack.

These go through actual routing + dependency resolution via ``TestClient`` (orgs are
simulated with ``app.dependency_overrides`` on ``get_current_org`` — not a hand-built
request), so they cover the route contract end to end: status codes, the concurrency and
batch guards, and the org-scoped default-deny on GET /jobs.

DB-backed (Postgres-only types) — uses the shared ``pg_session`` fixture, so they skip
without ``TEST_DATABASE_URL`` and stay green offline. ``schedule_job`` is stubbed so the
route creates + commits the job row through the real stack without spawning the async
worker (the worker itself is covered in test_generation_jobs.py).
"""
import uuid

import pytest

pytest.importorskip("httpx")  # FastAPI TestClient needs httpx (dev/test-only dep)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import get_session  # noqa: E402
from app.db.models import GenerationJob, Organization, Question, Questionnaire  # noqa: E402
from app.deps import get_current_org  # noqa: E402
from app.main import app  # noqa: E402


def _org(session, prefix: str = "org") -> Organization:
    org = Organization(name=prefix, slug=f"{prefix}-{uuid.uuid4().hex[:8]}")
    session.add(org)
    session.flush()
    return org


def _questionnaire(session, org: Organization, n_questions: int) -> Questionnaire:
    qn = Questionnaire(org_id=org.id, title="T", status="uploaded")
    session.add(qn)
    session.flush()
    for i in range(n_questions):
        session.add(
            Question(org_id=org.id, questionnaire_id=qn.id, text=f"Q{i}?", row_index=i)
        )
    session.flush()
    return qn


def _as(org: Organization) -> None:
    """Make subsequent requests act as `org` (the auth seam, simulated)."""
    app.dependency_overrides[get_current_org] = lambda: org


@pytest.fixture
def client(pg_session, monkeypatch):
    # Assert the endpoint contract only; don't spawn the real async worker here (it's tested
    # in test_generation_jobs.py). The job row is still created + committed via the stack.
    monkeypatch.setattr("app.questionnaires.jobs.schedule_job", lambda *a, **k: None)
    app.dependency_overrides[get_session] = lambda: pg_session
    try:
        yield TestClient(app)  # no `with`: skip lifespan (it would hit the app's own DB)
    finally:
        app.dependency_overrides.clear()


def test_generate_returns_202_with_job_id(client, pg_session):
    org = _org(pg_session)
    qn = _questionnaire(pg_session, org, 3)
    _as(org)

    resp = client.post(f"/questionnaires/{qn.id}/generate", json={})
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    # A real, org-scoped pending job row was created through the route.
    job = pg_session.scalar(select(GenerationJob).where(GenerationJob.id == uuid.UUID(job_id)))
    assert job is not None
    assert job.org_id == org.id and job.status == "pending" and job.total == 3


def test_second_concurrent_generate_conflicts_409(client, pg_session):
    org = _org(pg_session)
    qn = _questionnaire(pg_session, org, 2)
    _as(org)

    assert client.post(f"/questionnaires/{qn.id}/generate", json={}).status_code == 202
    assert client.post(f"/questionnaires/{qn.id}/generate", json={}).status_code == 409


def test_generate_over_batch_cap_422(client, pg_session, monkeypatch):
    monkeypatch.setattr(settings, "max_generation_batch", 2)
    org = _org(pg_session)
    qn = _questionnaire(pg_session, org, 3)  # 3 > cap of 2
    _as(org)

    assert client.post(f"/questionnaires/{qn.id}/generate", json={}).status_code == 422


def test_get_job_owning_org_200(client, pg_session):
    org = _org(pg_session)
    qn = _questionnaire(pg_session, org, 1)
    job = GenerationJob(
        org_id=org.id, questionnaire_id=qn.id, status="running", total=5, completed=2
    )
    pg_session.add(job)
    pg_session.flush()
    _as(org)

    resp = client.get(f"/jobs/{job.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "running"
    assert body["total"] == 5 and body["completed"] == 2 and body["error"] is None


def test_get_job_other_org_404(client, pg_session):
    org_a = _org(pg_session, "a")
    org_b = _org(pg_session, "b")
    qn_b = _questionnaire(pg_session, org_b, 1)
    job_b = GenerationJob(
        org_id=org_b.id, questionnaire_id=qn_b.id, status="running", total=3, completed=1
    )
    pg_session.add(job_b)
    pg_session.flush()

    # org A must not be able to read org B's job — default deny, no existence leak.
    _as(org_a)
    assert client.get(f"/jobs/{job_b.id}").status_code == 404
    # org B reads its own.
    _as(org_b)
    assert client.get(f"/jobs/{job_b.id}").status_code == 200


def test_get_job_unknown_id_404(client, pg_session):
    _as(_org(pg_session))
    assert client.get(f"/jobs/{uuid.uuid4()}").status_code == 404
