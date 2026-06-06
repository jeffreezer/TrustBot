"""Durable, pollable background draft-generation jobs (Phase 6).

Right-sized async: an **in-process** ``asyncio`` task runs the (blocking) generation off
the event loop via ``asyncio.to_thread`` in its own DB session, committing answer-by-answer
and bumping a ``generation_jobs`` row so the UI can poll N/total. No external queue
(Celery/Redis) — that's future scaling work, noted in ARCHITECTURE.md. Because the worker
lives in the process, a restart kills it; ``fail_orphaned_jobs`` (run at startup) marks any
left-over pending/running job as failed so nothing shows as forever-running.

Security: every user-facing read of a job is org-scoped at the route; this module's worker
loads a job by its (random, non-guessable) id and acts on its own ``org_id``. ``error`` is a
generic string only — never a stack trace, provider response, or secret/PII; logs carry the
job id and exception *type name* only.
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import SessionLocal
from ..db.models import GenerationJob, Organization, Question, Questionnaire
from ..providers import GenerationProvider
from .service import generate_drafts

logger = logging.getLogger("trustbot.jobs")

ACTIVE_STATUSES: tuple[str, ...] = ("pending", "running")

# Background tasks are kept referenced so the event loop doesn't GC them mid-run.
_BACKGROUND_TASKS: set[asyncio.Task] = set()


class ConcurrentJobError(Exception):
    """A generation job is already active for this questionnaire."""


class BatchTooLargeError(Exception):
    """The questionnaire exceeds MAX_GENERATION_BATCH questions."""


def create_generation_job(
    session: Session, *, org: Organization, questionnaire_id: uuid.UUID
) -> GenerationJob:
    """Validate and create a pending job row (caller commits).

    Raises ``LookupError`` (no such questionnaire in this org), ``BatchTooLargeError`` (over
    the cap), or ``ConcurrentJobError`` (one is already running for this questionnaire)."""
    questionnaire = session.scalar(
        select(Questionnaire).where(
            Questionnaire.id == questionnaire_id, Questionnaire.org_id == org.id
        )
    )
    if questionnaire is None:
        raise LookupError("questionnaire not found")

    total = session.scalar(
        select(func.count())
        .select_from(Question)
        .where(Question.questionnaire_id == questionnaire_id, Question.org_id == org.id)
    ) or 0

    if total > settings.max_generation_batch:
        raise BatchTooLargeError(
            f"questionnaire has {total} questions; the per-job limit is "
            f"{settings.max_generation_batch}"
        )

    active = session.scalar(
        select(GenerationJob).where(
            GenerationJob.questionnaire_id == questionnaire_id,
            GenerationJob.org_id == org.id,
            GenerationJob.status.in_(ACTIVE_STATUSES),
        )
    )
    if active is not None:
        raise ConcurrentJobError("a generation job is already running for this questionnaire")

    job = GenerationJob(
        org_id=org.id,
        questionnaire_id=questionnaire_id,
        status="pending",
        total=total,
        completed=0,
    )
    session.add(job)
    session.flush()
    return job


def _execute_job(
    session: Session,
    *,
    job: GenerationJob,
    regenerate: bool,
    generator: GenerationProvider | None = None,
) -> None:
    """Run a job to completion on the given session (the testable core).

    Sets status=running, drafts via ``generate_drafts`` (which commits per answer) while
    bumping ``completed`` after each, and lands done/failed. Caller owns the session."""
    job.status = "running"
    session.commit()

    org = session.get(Organization, job.org_id)

    def on_progress(processed: int, _total: int) -> None:
        job.completed = processed
        session.commit()

    try:
        result = generate_drafts(
            session,
            org=org,
            questionnaire_id=job.questionnaire_id,
            regenerate=regenerate,
            generator=generator,
            on_progress=on_progress,
        )
    except Exception as exc:  # noqa: BLE001 - mark failed with a generic message, no detail
        session.rollback()
        job.status = "failed"
        job.error = "generation failed"
        session.commit()
        logger.warning("generation job %s failed (%s)", job.id, type(exc).__name__)
        return

    job.completed = job.total
    job.status = "done"
    if result.get("failed"):
        job.error = (
            f"{result['failed']} of {result['total']} question(s) could not be drafted"
        )
    session.commit()


def run_job(job_id: uuid.UUID, *, regenerate: bool) -> None:
    """Thread entrypoint: open a fresh session and execute the job. Self-contained."""
    session = SessionLocal()
    try:
        job = session.get(GenerationJob, job_id)
        if job is None:
            return
        _execute_job(session, job=job, regenerate=regenerate)
    finally:
        session.close()


def fail_orphaned_jobs(session: Session) -> int:
    """Mark any pending/running jobs as failed (run at startup; caller commits).

    System maintenance — spans all orgs by design, so a worker killed by a restart never
    leaves a job stuck 'running'."""
    orphans = session.scalars(
        select(GenerationJob).where(GenerationJob.status.in_(ACTIVE_STATUSES))
    ).all()
    for job in orphans:
        job.status = "failed"
        job.error = "interrupted by restart"
    return len(orphans)


def schedule_job(job_id: uuid.UUID, *, regenerate: bool) -> None:
    """Spawn the background worker on the running event loop (call from an async route)."""
    task = asyncio.create_task(_run_async(job_id, regenerate=regenerate))
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


async def _run_async(job_id: uuid.UUID, *, regenerate: bool) -> None:
    # Offload the blocking generation (model inference + HTTP) to a thread so the event
    # loop stays free to serve job-status polls.
    await asyncio.to_thread(run_job, job_id, regenerate=regenerate)
