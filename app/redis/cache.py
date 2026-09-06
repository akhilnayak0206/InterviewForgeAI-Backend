"""Cache-aside pattern implementation.

The cache-aside pattern puts the application in charge of caching:

    Read path:
        1. Check Redis for key
        2. HIT  → deserialize and return (fast path, ~0.1ms)
        3. MISS → call fetch_fn() to get data from source
        4. Serialize result, store in Redis with TTL
        5. Return result

    Write path (invalidation):
        1. Write to PostgreSQL (source of truth)
        2. Delete cache key in Redis
        3. Next read triggers a cache miss → fresh data

Redis failures are always caught and logged. On failure:
    - Reads fall back to the data source (slower but correct)
    - Writes skip cache invalidation (may serve stale data briefly)
    - The application NEVER crashes due to Redis

This is the simplest caching pattern and the right default for most
read-heavy workloads. More complex patterns (write-through, write-back)
add consistency guarantees at the cost of complexity. Cache-aside with
explicit invalidation is sufficient for this project.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def cache_get_or_set(
    redis: Redis | None,
    key: str,
    fetch_fn: Callable[[], T | Awaitable[T]],
    *,
    ttl: int = 600,
    serializer: Callable[[Any], str] = json.dumps,
    deserializer: Callable[[str], Any] = json.loads,
) -> T:
    """Cache-aside: get from cache or fetch and cache.

    This is the primary caching function. It handles:
        - Cache hit (return cached value)
        - Cache miss (call fetch_fn, cache result, return)
        - Redis unavailable (call fetch_fn directly)
        - Serialization/deserialization

    Args:
        redis: The Redis client (None if unavailable).
        key: Cache key (use keys.py builders).
        fetch_fn: Function that retrieves the data from the source.
            Can be sync or async. This is called on cache miss.
        ttl: Time-to-live in seconds. After this, the key expires
            and the next request triggers a fresh fetch.
        serializer: Converts the value to a string for Redis storage.
            Default: json.dumps. Override for custom types.
        deserializer: Converts the Redis string back to the value.
            Default: json.loads.

    Returns:
        The cached or freshly fetched value.
    """
    # — Try cache first —
    if redis is not None:
        try:
            cached = await redis.get(key)
            if cached is not None:
                logger.debug("Cache HIT | key=%s", key)
                return deserializer(cached)
            logger.debug("Cache MISS | key=%s", key)
        except RedisError as e:
            logger.warning("Cache read failed | key=%s | error=%s", key, str(e))

    # — Cache miss or Redis unavailable: fetch from source —
    import asyncio

    raw_result = fetch_fn()
    if asyncio.iscoroutine(raw_result) or asyncio.isfuture(raw_result):
        raw_result = await raw_result

    result: T = raw_result  # type: ignore[assignment]

    # — Populate cache for next time —
    if redis is not None:
        try:
            await redis.set(key, serializer(result), ex=ttl)
            logger.debug("Cache SET | key=%s | ttl=%ds", key, ttl)
        except RedisError as e:
            logger.warning("Cache write failed | key=%s | error=%s", key, str(e))

    return result


async def cache_delete(redis: Redis | None, key: str) -> bool:
    """Delete a cache key (invalidation).

    Called after a write to PostgreSQL to ensure the next read
    fetches fresh data.

    Returns True if the key was deleted, False if it didn't exist
    or Redis was unavailable.
    """
    if redis is None:
        return False

    try:
        deleted = await redis.delete(key)
        if deleted:
            logger.debug("Cache DELETE | key=%s", key)
        return deleted > 0
    except RedisError as e:
        logger.warning("Cache delete failed | key=%s | error=%s", key, str(e))
        return False


async def cache_delete_pattern(redis: Redis | None, pattern: str) -> int:
    """Delete all keys matching a pattern (bulk invalidation).

    Uses SCAN (not KEYS) to avoid blocking Redis. SCAN is O(1) per
    call and iterates through keys incrementally.

    Use case: invalidate all RAG cache for a user when their
    documents are re-embedded.

    Args:
        redis: The Redis client.
        pattern: Glob pattern (e.g., "cache:rag:user-123:*").

    Returns:
        Number of keys deleted.
    """
    if redis is None:
        return 0

    deleted_count = 0
    try:
        async for key in redis.scan_iter(match=pattern, count=100):
            await redis.delete(key)
            deleted_count += 1

        if deleted_count > 0:
            logger.info(
                "Cache bulk DELETE | pattern=%s | deleted=%d",
                pattern,
                deleted_count,
            )
    except RedisError as e:
        logger.warning(
            "Cache bulk delete failed | pattern=%s | error=%s",
            pattern,
            str(e),
        )

    return deleted_count
