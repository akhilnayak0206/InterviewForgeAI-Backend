"""Redis connection pool — async client for application-level Redis.

This module manages a SINGLE shared Redis connection pool for the
entire FastAPI process. It is separate from the ARQ pool in
app/jobs/queue.py because:

    1. ARQ manages its own connection lifecycle.
    2. Application Redis (cache, rate limit, locks) has different
       connection settings and usage patterns.
    3. If we ever move the job queue to a separate Redis instance,
       the application Redis is unaffected.

Connection lifecycle:
    - init_redis_pool() is called during FastAPI startup (lifespan)
    - get_redis_client() returns the shared pool for use in requests
    - close_redis_pool() is called during FastAPI shutdown (lifespan)

Why a pool?
    Each Redis command needs a TCP connection. Opening a new connection
    per request (~1ms handshake) wastes time and file descriptors.
    A pool keeps N connections open and lends them to callers.

Why async?
    This is an async FastAPI application. Using the synchronous Redis
    client would block the event loop during I/O. redis.asyncio.Redis
    uses non-blocking I/O that cooperates with asyncio.
"""

from __future__ import annotations

import logging

from redis.asyncio import ConnectionPool, Redis

from app.core.config import settings

logger = logging.getLogger(__name__)

# Module-level pool and client. Initialized lazily via init_redis_pool().
_pool: ConnectionPool | None = None
_client: Redis | None = None


async def init_redis_pool() -> None:
    """Initialize the shared Redis connection pool.

    Called once during FastAPI startup. Creates the connection pool
    and a Redis client bound to it. Does NOT open connections yet —
    connections are created on demand up to max_connections.

    If Redis is unreachable at startup, we log a warning but do NOT
    crash the application. Redis is an optimization layer, not a
    hard dependency. Features that depend on Redis will fall back
    gracefully (see cache.py, rate_limit.py).
    """
    global _pool, _client

    try:
        _pool = ConnectionPool(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_CACHE_DB,
            max_connections=settings.REDIS_MAX_CONNECTIONS,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )

        _client = Redis(connection_pool=_pool)

        # Verify connectivity with a PING
        await _client.ping()
        logger.info(
            "Redis pool initialized | host=%s | port=%d | db=%d",
            settings.REDIS_HOST,
            settings.REDIS_PORT,
            settings.REDIS_CACHE_DB,
        )

    except Exception as e:
        logger.warning(
            "Redis unavailable at startup — features will degrade | error=%s",
            str(e),
        )
        # Don't crash. Set to None so get_redis_client() returns None.
        _pool = None
        _client = None


def get_redis_client() -> Redis | None:
    """Return the shared Redis client, or None if unavailable.

    Every caller MUST handle None gracefully. This is by design:
    Redis is never a hard dependency.
    """
    return _client


async def close_redis_pool() -> None:
    """Close the Redis connection pool. Called during app shutdown."""
    global _pool, _client

    if _client is not None:
        await _client.aclose()
        _client = None

    if _pool is not None:
        await _pool.disconnect()
        _pool = None

    logger.info("Redis pool closed")
