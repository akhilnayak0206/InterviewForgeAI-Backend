"""Job service — CRUD operations on the Job table.

This service manages job RECORDS, not job EXECUTION.
It is called by:
    - Producers (FastAPI routes) to create jobs
    - Workers to update job status
    - API routes to query job status for clients

Design decisions:
    - create_job() does NOT enqueue to Redis. Enqueueing is a
      separate step so the DB record exists BEFORE the queue message.
      If Redis is down, we still have the job in PostgreSQL.
    - mark_running/completed/failed are explicit transitions, not a
      generic "update status" method. This enforces the state machine
      and makes it impossible to accidentally skip a state.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, func, select

from app.jobs.enums import JobStatus, JobType
from app.models.job import Job

logger = logging.getLogger(__name__)


def create_job(
    *,
    db: Session,
    user_id: uuid.UUID,
    job_type: JobType,
    payload: dict,
    max_attempts: int = 3,
) -> Job:
    """Create a new job record in PENDING status.

    This does NOT enqueue the job. The caller is responsible for
    enqueuing after the DB record is committed. This ordering is
    intentional: if enqueueing fails, the job still exists in the
    database and can be picked up by a recovery sweep.
    """
    job = Job(
        user_id=user_id,
        job_type=job_type,
        status=JobStatus.pending,
        payload=payload,
        max_attempts=max_attempts,
    )

    db.add(job)
    db.commit()
    db.refresh(job)

    logger.info(
        "Job created | id=%s | type=%s | user=%s",
        job.id,
        job_type,
        user_id,
    )

    return job


def mark_running(*, db: Session, job_id: uuid.UUID) -> Job | None:
    """Transition a job to RUNNING status.

    Called by the worker when it picks up a job.
    Sets started_at and increments the attempt counter.

    Returns None if the job doesn't exist (shouldn't happen, but
    defensive programming for distributed systems).
    """
    job = db.get(Job, job_id)
    if not job:
        logger.error("mark_running: job not found | id=%s", job_id)
        return None

    job.status = JobStatus.running
    job.started_at = datetime.now(UTC)
    job.attempts += 1
    job.error = None  # Clear error from previous attempt

    db.commit()
    db.refresh(job)

    logger.info(
        "Job running | id=%s | attempt=%d/%d",
        job_id,
        job.attempts,
        job.max_attempts,
    )

    return job


def mark_completed(*, db: Session, job_id: uuid.UUID, result: dict) -> Job | None:
    """Transition a job to COMPLETED status.

    Called by the worker when the task function succeeds.
    """
    job = db.get(Job, job_id)
    if not job:
        logger.error("mark_completed: job not found | id=%s", job_id)
        return None

    job.status = JobStatus.completed
    job.result = result
    job.completed_at = datetime.now(UTC)
    job.error = None

    db.commit()
    db.refresh(job)

    logger.info("Job completed | id=%s", job_id)

    return job


def mark_failed(*, db: Session, job_id: uuid.UUID, error: str) -> Job | None:
    """Transition a job to FAILED or DEAD status.

    If attempts < max_attempts → FAILED (will be retried).
    If attempts >= max_attempts → DEAD (permanent failure).

    The retry mechanism re-enqueues FAILED jobs. DEAD jobs require
    manual investigation.
    """
    job = db.get(Job, job_id)
    if not job:
        logger.error("mark_failed: job not found | id=%s", job_id)
        return None

    job.error = error

    if job.attempts >= job.max_attempts:
        job.status = JobStatus.dead
        job.completed_at = datetime.now(UTC)
        logger.error(
            "Job dead (max attempts) | id=%s | attempts=%d | error=%s",
            job_id,
            job.attempts,
            error,
        )
    else:
        job.status = JobStatus.failed
        logger.warning(
            "Job failed (will retry) | id=%s | attempt=%d/%d | error=%s",
            job_id,
            job.attempts,
            job.max_attempts,
            error,
        )

    db.commit()
    db.refresh(job)

    return job


def update_progress(
    *,
    db: Session,
    job_id: uuid.UUID,
    progress: int,
    message: str | None = None,
) -> None:
    """Update a job's progress percentage and stage label.

    Called by task functions at meaningful milestones.
    Commits immediately so the client can see updates via polling.

    Args:
        progress: 0-100 integer percentage.
        message: human-readable stage (e.g., "Generating embeddings").
    """
    job = db.get(Job, job_id)
    if not job:
        return

    job.progress = min(100, max(0, progress))
    job.progress_message = message
    db.commit()


def get_job(*, db: Session, job_id: uuid.UUID) -> Job | None:
    """Fetch a job by ID."""
    return db.get(Job, job_id)


def get_job_for_user(
    *,
    db: Session,
    job_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Job | None:
    """Fetch a job by ID, scoped to a specific user.

    Returns None if the job doesn't exist or belongs to another user.
    Multi-tenant isolation: users can only see their own jobs.
    """
    job = db.get(Job, job_id)
    if not job or job.user_id != user_id:
        return None
    return job


def get_jobs_by_user(
    *,
    db: Session,
    user_id: uuid.UUID,
    job_type: JobType | None = None,
    status: JobStatus | None = None,
    offset: int = 0,
    limit: int = 20,
) -> tuple[Sequence[Job], int]:
    """Fetch paginated jobs for a user with optional filters.

    Same pattern as document_service.get_documents_by_user.
    """
    base = select(Job).where(Job.user_id == user_id)

    if job_type is not None:
        base = base.where(Job.job_type == job_type)

    if status is not None:
        base = base.where(Job.status == status)

    total = db.exec(select(func.count()).select_from(base.subquery())).one()
    items = db.exec(base.order_by(Job.created_at.desc()).offset(offset).limit(limit)).all()

    return items, total


def get_retryable_jobs(*, db: Session, limit: int = 50) -> Sequence[Job]:
    """Fetch jobs in FAILED status that can be retried.

    Used by the recovery sweep to re-enqueue failed jobs.
    Only returns jobs where attempts < max_attempts.
    """
    stmt = (
        select(Job)
        .where(
            Job.status == JobStatus.failed,
            Job.attempts < Job.max_attempts,
        )
        .order_by(Job.created_at.asc())
        .limit(limit)
    )

    return db.exec(stmt).all()


def get_stuck_jobs(
    *,
    db: Session,
    stuck_threshold_minutes: int = 30,
    limit: int = 50,
) -> Sequence[Job]:
    """Fetch jobs that have been RUNNING for too long.

    If a worker picks up a job and then crashes, the job stays in
    RUNNING status forever. This query finds those zombies so they
    can be reset to PENDING or FAILED.
    """
    cutoff = datetime.now(UTC) - timedelta(minutes=stuck_threshold_minutes)

    stmt = (
        select(Job)
        .where(
            Job.status == JobStatus.running,
            Job.started_at < cutoff,
        )
        .order_by(Job.started_at.asc())
        .limit(limit)
    )

    return db.exec(stmt).all()
