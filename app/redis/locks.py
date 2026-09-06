"""Distributed lock using Redis SET NX EX.

When to use:
    - Prevent two workers from embedding the same document
    - Prevent duplicate report generation for the same session
    - Any expensive operation where concurrent duplicates waste resources

When NOT to use:
    - Normal request handling (too much overhead)
    - Read operations (no conflict)
    - Operations that are already idempotent (duplicates are harmless)

How it works:
    SET lock:embed:{doc_id} {owner_token} NX EX {ttl}

    NX = "set only if Not eXists"
        → Only one caller wins. Everyone else gets None.

    EX = "expire after ttl seconds"
        → If the lock holder crashes without releasing, the lock
          auto-releases after ttl. This prevents permanent deadlocks.

    owner_token = a random UUID
        → Only the lock holder can release its own lock. This prevents
          a slow holder from accidentally releasing a lock that was
          already acquired by someone else after expiry.

Release uses a Lua script for atomicity:
    if redis.call("GET", key) == owner_token then
        redis.call("DEL", key)
    end

    Without the Lua script, there's a race between GET and DEL:
    1. Holder A reads key → sees its own token
    2. Lock expires
    3. Holder B acquires the lock
    4. Holder A deletes the key → accidentally releases B's lock

    The Lua script executes atomically on the Redis server.

This is NOT a Redlock implementation. Redlock is designed for Redis
Cluster with multiple independent masters. For a single Redis instance,
this simple approach is correct and sufficient.
"""

from __future__ import annotations

import logging
import uuid

from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

# Lua script for safe lock release.
# Only deletes the key if the stored value matches the owner token.
_RELEASE_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
else
    return 0
end
"""


async def acquire_lock(
    redis: Redis | None,
    key: str,
    *,
    ttl: int = 30,
    owner: str | None = None,
) -> str | None:
    """Attempt to acquire a distributed lock.

    Args:
        redis: The Redis client. If None, lock acquisition is skipped
            (caller should proceed without lock — fail open).
        key: Lock key (use keys.lock_key() builder).
        ttl: Lock expiration in seconds. The lock auto-releases after
            this time even if the holder doesn't call release_lock().
            Choose a TTL longer than the expected operation duration.
        owner: Optional owner identifier. If not provided, a random
            UUID is generated. The owner token is required to release
            the lock — only the holder can release it.

    Returns:
        The owner token if the lock was acquired, None if:
            - Another holder already has the lock
            - Redis is unavailable
    """
    if redis is None:
        logger.warning("Lock skipped (Redis unavailable) | key=%s", key)
        return None

    token = owner or uuid.uuid4().hex

    try:
        acquired = await redis.set(key, token, nx=True, ex=ttl)

        if acquired:
            logger.debug("Lock ACQUIRED | key=%s | ttl=%ds", key, ttl)
            return token

        logger.debug("Lock CONTENTION | key=%s (already held)", key)
        return None

    except RedisError as e:
        logger.warning(
            "Lock acquire failed (Redis error) | key=%s | error=%s",
            key,
            str(e),
        )
        return None


async def release_lock(
    redis: Redis | None,
    key: str,
    owner: str,
) -> bool:
    """Release a distributed lock.

    Only releases the lock if the caller is the current owner.
    Uses a Lua script for atomicity (GET + DEL in one operation).

    Args:
        redis: The Redis client.
        key: Lock key (same key used in acquire_lock).
        owner: The owner token returned by acquire_lock().
            If this doesn't match the stored value, the lock
            is NOT released (it belongs to someone else).

    Returns:
        True if the lock was released, False otherwise.
    """
    if redis is None:
        return False

    try:
        result = await redis.eval(_RELEASE_SCRIPT, 1, key, owner)
        released = result == 1

        if released:
            logger.debug("Lock RELEASED | key=%s", key)
        else:
            logger.debug("Lock release SKIPPED (not owner) | key=%s", key)

        return released

    except RedisError as e:
        logger.warning(
            "Lock release failed (Redis error) | key=%s | error=%s",
            key,
            str(e),
        )
        return False
