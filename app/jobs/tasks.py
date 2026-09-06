"""Job task functions — the actual work that workers execute.

Architecture principle:
    Task functions are THIN WRAPPERS around existing service code.
    They do NOT contain business logic. They:
        1. Read the job record from PostgreSQL
        2. Call the existing service function
        3. Return the result

    This keeps business logic in the service layer where it belongs,
    and makes tasks testable by mocking the service.

    The embed_document_task() function calls the same
    embedding_pipeline.embed_document() that the synchronous route
    used to call. The pipeline code doesn't know or care whether
    it's being called from an HTTP request or a background worker.

Idempotency (Part 9):
    The embedding pipeline already handles re-indexing:
        - _delete_existing_chunks() removes old chunks before creating new ones
        - Status transitions are explicit (processed → embedding → indexed)
    If a job runs twice, it re-embeds cleanly. No duplicate chunks.
    This is idempotent by design, not by accident.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from typing import Any

from app.db.session import SessionLocal
from app.documents import embedding_pipeline
from app.documents.models import Document
from app.jobs.enums import JobStatus, JobType
from app.services import job as job_service

logger = logging.getLogger(__name__)


# — Task Registry —
# Maps JobType → handler function. The worker dispatcher uses this.
# Adding a new job type? Add the handler here and implement the function below.
TASK_REGISTRY: dict[str, Callable[..., Any]] = {}


def register_task(job_type: JobType):
    """Decorator to register a task handler for a job type."""

    def decorator(func):
        TASK_REGISTRY[job_type.value] = func
        return func

    return decorator


@register_task(JobType.embed_document)
def embed_document_task(*, job_id: uuid.UUID, payload: dict) -> dict:
    """Background task: embed a document.

    This is the same work that POST /documents/{id}/embed used to do
    synchronously. Now it runs in a worker process.

    Payload:
        {"document_id": "uuid-string"}

    Returns:
        {"chunks_created": int, "total_tokens": int}

    Idempotency:
        Safe to run multiple times. The pipeline deletes existing
        chunks before creating new ones (see _delete_existing_chunks
        in embedding_pipeline.py).
    """
    document_id = uuid.UUID(payload["document_id"])

    logger.info(
        "embed_document_task starting | job_id=%s | document_id=%s",
        job_id,
        document_id,
    )

    # Each task gets its own DB session. Workers are separate processes
    # and MUST NOT share sessions with FastAPI or other workers.
    with SessionLocal() as db:
        job_service.update_progress(
            db=db,
            job_id=job_id,
            progress=10,
            message="Loading document",
        )

        document = db.get(Document, document_id)

        if not document:
            raise ValueError(f"Document not found: {document_id}")

        job_service.update_progress(
            db=db,
            job_id=job_id,
            progress=25,
            message="Starting embedding pipeline",
        )

        # Call the EXISTING pipeline. No business logic duplication.
        result = embedding_pipeline.embed_document(db=db, document=document)

        if not result.success:
            raise RuntimeError(f"Embedding failed: {result.error}")

        job_service.update_progress(
            db=db,
            job_id=job_id,
            progress=100,
            message="Complete",
        )

        return {
            "chunks_created": result.chunks_created,
            "total_tokens": result.total_tokens,
            "document_id": str(result.document_id),
        }


async def execute_job(ctx: dict, job_id_str: str) -> None:
    """Universal ARQ handler — dispatches to the correct task function.

    This is the ONLY function ARQ knows about. It:
        1. Looks up the Job record in PostgreSQL
        2. Marks it as RUNNING
        3. Dispatches to the correct task handler based on job_type
        4. Marks it as COMPLETED or FAILED

    Why a single dispatch function instead of one ARQ function per job type?
        - Centralized lifecycle management (mark_running, mark_completed, mark_failed)
        - Centralized error handling and logging
        - Job state lives in PostgreSQL, not in ARQ's Redis result store
        - Adding a new job type = adding a handler + registry entry, not
          modifying ARQ configuration
    """
    job_id = uuid.UUID(job_id_str)

    with SessionLocal() as db:
        # — Step 1: Load job record —
        job = job_service.get_job(db=db, job_id=job_id)

        if not job:
            logger.error("execute_job: job not found | id=%s", job_id)
            return

        # — Guard: skip if already completed or dead —
        if job.status in (JobStatus.completed, JobStatus.dead):
            logger.warning(
                "execute_job: skipping (status=%s) | id=%s",
                job.status,
                job_id,
            )
            return

        # — Step 2: Mark as running —
        job = job_service.mark_running(db=db, job_id=job_id)
        if not job:
            return

        # — Step 3: Dispatch to handler —
        handler = TASK_REGISTRY.get(job.job_type)

        if not handler:
            job_service.mark_failed(
                db=db,
                job_id=job_id,
                error=f"No handler registered for job type: {job.job_type}",
            )
            return

        try:
            result = handler(job_id=job_id, payload=job.payload)

            # — Step 4a: Success —
            job_service.mark_completed(db=db, job_id=job_id, result=result)

        except Exception as e:
            # — Step 4b: Failure —
            logger.exception(
                "Job execution failed | id=%s | type=%s | attempt=%d",
                job_id,
                job.job_type,
                job.attempts,
            )

            job_service.mark_failed(db=db, job_id=job_id, error=str(e))

            # If the job is retryable (failed, not dead), re-enqueue
            # with exponential backoff.
            db.refresh(job)
            if job.status == JobStatus.failed:
                from app.jobs.queue import enqueue_job

                backoff_seconds = 2**job.attempts  # 2, 4, 8, 16...
                await enqueue_job(
                    job_id=job_id,
                    job_type=job.job_type,
                    defer_seconds=backoff_seconds,
                )

                logger.info(
                    "Job re-enqueued for retry | id=%s | backoff=%ds",
                    job_id,
                    backoff_seconds,
                )
