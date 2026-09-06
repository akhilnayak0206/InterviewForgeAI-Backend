"""Queue configuration — ARQ connection to Redis.

This module provides:
    - get_redis_settings(): ARQ's RedisSettings for connecting to Redis
    - enqueue_job(): enqueue a job for background processing

Redis is used here ONLY as a job queue broker. It delivers messages
from producers (FastAPI) to consumers (workers). Application state
lives in PostgreSQL.

ARQ's role:
    - Serialize the job function name + arguments
    - Put them in a Redis list
    - Workers poll the list and execute the function
    - Store the result briefly in Redis (for ARQ's internal tracking)

Our role:
    - Maintain durable job state in PostgreSQL (the Job table)
    - Handle retries, idempotency, and failure recovery at the
      application level, not the queue level
"""

from __future__ import annotations

import logging
import uuid

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.core.config import settings

logger = logging.getLogger(__name__)

# Module-level connection pool. Initialized lazily on first use.
_arq_pool: ArqRedis | None = None


def get_redis_settings() -> RedisSettings:
    """Build ARQ RedisSettings from application configuration."""
    return RedisSettings(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        database=settings.REDIS_DB,
    )


async def get_arq_pool() -> ArqRedis:
    """Get or create the ARQ Redis connection pool.

    Lazily initialized so we don't connect to Redis at import time.
    The pool is reused across all enqueue calls within the FastAPI process.
    """
    global _arq_pool

    if _arq_pool is None:
        _arq_pool = await create_pool(get_redis_settings())

    return _arq_pool


async def enqueue_job(
    *,
    job_id: uuid.UUID,
    job_type: str,
    defer_seconds: int = 0,
) -> str | None:
    """Enqueue a job for background processing.

    Args:
        job_id: The PostgreSQL Job.id. The worker uses this to look up
            the job record and its payload. We do NOT pass the payload
            through Redis — the worker reads it from PostgreSQL.
            This keeps Redis messages small and PostgreSQL as the
            source of truth.
        job_type: The JobType value, used as the ARQ function name.
        defer_seconds: Optional delay before the job becomes available.
            Used for retry backoff (e.g., retry in 4 seconds).

    Returns:
        The ARQ job ID if enqueued, None if enqueue failed.
    """
    pool = await get_arq_pool()

    try:
        arq_job = await pool.enqueue_job(
            "execute_job",  # The single ARQ handler function
            str(job_id),
            _defer_by=defer_seconds if defer_seconds > 0 else None,
        )

        if arq_job is None:
            logger.warning(
                "Job enqueue returned None (possible duplicate) | job_id=%s",
                job_id,
            )
            return None

        logger.info(
            "Job enqueued | job_id=%s | type=%s | defer=%ds",
            job_id,
            job_type,
            defer_seconds,
        )

        return arq_job.job_id

    except Exception as e:
        logger.error(
            "Failed to enqueue job | job_id=%s | error=%s",
            job_id,
            str(e),
        )
        return None


async def close_arq_pool() -> None:
    """Close the ARQ Redis connection pool. Called during app shutdown."""
    global _arq_pool

    if _arq_pool is not None:
        await _arq_pool.aclose()
        _arq_pool = None
        logger.info("ARQ Redis pool closed")
