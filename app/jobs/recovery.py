"""Job recovery — handles stuck and failed jobs.

This module provides recovery functions for jobs that get stuck due to
worker crashes, database failures, or other infrastructure problems.

Usage:
    Run the recovery sweep periodically (e.g., every 5 minutes via
    ARQ's cron functionality or a manual script):

        python -m app.jobs.recovery

    Or call recover_stuck_jobs() from a health-check endpoint.

Design decisions:
    - Stuck jobs are reset to FAILED (not PENDING) so the retry
      mechanism handles them with proper backoff.
    - Recovery only processes a limited batch to avoid overloading
      the system after an outage.
    - All recovery actions are logged for post-incident investigation.
"""

from __future__ import annotations

import asyncio
import logging

from app.db.session import SessionLocal
from app.jobs.enums import JobStatus
from app.jobs.queue import enqueue_job
from app.services import job as job_service

logger = logging.getLogger(__name__)


async def recover_stuck_jobs(stuck_threshold_minutes: int = 30) -> int:
    """Find and reset jobs stuck in RUNNING status.

    A job is "stuck" if it's been RUNNING for longer than the threshold.
    This happens when a worker dies mid-execution.

    Recovery strategy:
        1. Find stuck jobs
        2. Mark each as FAILED (triggers normal retry flow)
        3. Re-enqueue with backoff if retryable

    Returns the number of jobs recovered.
    """
    recovered = 0

    with SessionLocal() as db:
        stuck_jobs = job_service.get_stuck_jobs(
            db=db,
            stuck_threshold_minutes=stuck_threshold_minutes,
        )

        if not stuck_jobs:
            logger.info("Recovery sweep: no stuck jobs found")
            return 0

        logger.warning(
            "Recovery sweep: found %d stuck jobs",
            len(stuck_jobs),
        )

        for job in stuck_jobs:
            job_service.mark_failed(
                db=db,
                job_id=job.id,
                error=f"Job stuck in RUNNING for >{stuck_threshold_minutes}min (worker crash?)",
            )

            db.refresh(job)

            # Re-enqueue if retryable
            if job.status == JobStatus.failed:
                backoff = 2**job.attempts
                await enqueue_job(
                    job_id=job.id,
                    job_type=job.job_type,
                    defer_seconds=backoff,
                )

            recovered += 1
            logger.info(
                "Recovered stuck job | id=%s | new_status=%s",
                job.id,
                job.status,
            )

    logger.info("Recovery sweep complete: %d jobs recovered", recovered)
    return recovered


async def requeue_failed_jobs() -> int:
    """Re-enqueue failed jobs that still have retry budget.

    Use this after an infrastructure incident: if Redis was down
    when retry was attempted, the job is FAILED but not in the queue.
    This function puts them back.

    Returns the number of jobs re-enqueued.
    """
    requeued = 0

    with SessionLocal() as db:
        failed_jobs = job_service.get_retryable_jobs(db=db)

        if not failed_jobs:
            logger.info("Requeue sweep: no retryable failed jobs")
            return 0

        for job in failed_jobs:
            backoff = 2**job.attempts
            result = await enqueue_job(
                job_id=job.id,
                job_type=job.job_type,
                defer_seconds=backoff,
            )

            if result:
                requeued += 1

    logger.info("Requeue sweep complete: %d jobs re-enqueued", requeued)
    return requeued


if __name__ == "__main__":
    """Run recovery sweeps manually.

    Usage: python -m app.jobs.recovery
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )

    async def main():
        stuck = await recover_stuck_jobs()
        requeued = await requeue_failed_jobs()
        print(f"Recovery complete: {stuck} stuck, {requeued} requeued")

    asyncio.run(main())
