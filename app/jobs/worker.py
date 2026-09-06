"""ARQ worker configuration.

This module defines the WorkerSettings class that ARQ uses to
configure and run worker processes. Start a worker with:

    arq app.jobs.worker.WorkerSettings

The worker:
    1. Connects to Redis using the same settings as FastAPI
    2. Polls for jobs enqueued by the API
    3. Calls execute_job() for each job
    4. execute_job() dispatches to the correct handler via TASK_REGISTRY

Worker lifecycle:
    - on_startup: runs when the worker starts (e.g., health log)
    - on_shutdown: runs when the worker stops (e.g., cleanup)

Concurrency:
    ARQ runs one job at a time per worker process by default.
    To run multiple jobs concurrently, increase max_jobs.
    Be careful: more concurrent jobs = more DB connections = more
    API calls. Match this to your database pool size and API rate limits.
"""

from __future__ import annotations

import logging

from app.jobs.queue import get_redis_settings
from app.jobs.tasks import execute_job

logger = logging.getLogger(__name__)


async def on_startup(ctx: dict) -> None:
    """Called when the worker process starts.

    Use this for one-time initialization: logging, health checks,
    verifying DB connectivity.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    logger.info("Worker started — ready to process jobs")


async def on_shutdown(ctx: dict) -> None:
    """Called when the worker process stops.

    Use this for cleanup: closing connections, flushing logs.
    """
    logger.info("Worker shutting down")


class WorkerSettings:
    """ARQ worker configuration.

    ARQ discovers this class and uses it to configure the worker.
    The class name MUST be WorkerSettings (ARQ convention).
    """

    # Functions the worker can execute. We use a single dispatch
    # function that routes to the correct handler based on job_type.
    functions = [execute_job]

    # Redis connection settings
    redis_settings = get_redis_settings()

    # Lifecycle hooks
    on_startup = on_startup
    on_shutdown = on_shutdown

    # — Concurrency —
    # Max concurrent jobs per worker process. Start with 5.
    # Each job opens its own DB session, so this also means
    # up to 5 concurrent DB connections per worker.
    max_jobs = 5

    # — Timeouts —
    # How long a single job can run before ARQ kills it.
    # Embedding a large document with retries could take up to 60s.
    # 300s (5 min) is generous but safe.
    job_timeout = 300

    # — Health checks —
    # ARQ writes a health check key to Redis every N seconds.
    # Monitoring systems can read this to verify workers are alive.
    health_check_interval = 30
