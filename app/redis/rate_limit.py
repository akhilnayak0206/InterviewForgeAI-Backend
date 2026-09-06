"""Sliding window rate limiter using Redis sorted sets.

Why sliding window (not fixed window)?
    Fixed window has a burst problem: a user can send max_requests at
    the end of one window and max_requests at the start of the next,
    doubling the effective rate. Sliding window tracks the actual
    count in a rolling time window — no boundary exploits.

How it works:
    Each request is stored as a member in a Redis sorted set.
    The score is the request timestamp. On each check:

    1. ZREMRANGEBYSCORE — remove entries older than the window
    2. ZADD — add the current request
    3. ZCARD — count entries in the set
    4. EXPIRE — set TTL for automatic cleanup

    All four commands run in a Redis pipeline (single round-trip,
    atomic execution). This prevents race conditions: two concurrent
    requests can't both read count=9, both add, and end up at 11.

Why not an in-memory Python dict?
    Multiple FastAPI processes (or containers) each have their own
    memory. A user hitting Process A and Process B bypasses both
    counters. Redis is shared — one counter for all processes.

Failure mode: FAIL OPEN.
    If Redis is unavailable, we allow the request through. Rationale:
    a short Redis outage is less harmful than blocking ALL users.
    We log aggressively so operators know rate limiting is degraded.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass

from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RateLimitResult:
    """Result of a rate limit check.

    Attributes:
        allowed: Whether the request is within the rate limit.
        current_count: Number of requests in the current window.
        max_requests: The limit for the window.
        window_seconds: Length of the sliding window.
        retry_after: Seconds until the oldest request in the window
            expires (useful for Retry-After header). 0 if allowed.
    """

    allowed: bool
    current_count: int
    max_requests: int
    window_seconds: int
    retry_after: int = 0


async def check_rate_limit(
    redis: Redis | None,
    key: str,
    *,
    max_requests: int,
    window_seconds: int,
) -> RateLimitResult:
    """Check and record a request against the sliding window rate limit.

    This function both CHECKS and RECORDS the request in one atomic
    operation. It does NOT just check — it also adds the current
    request to the window. This is intentional: separating check
    from record would create a TOCTOU race condition.

    Args:
        redis: The Redis client. If None, fail open.
        key: Rate limit key (use keys.py builders).
        max_requests: Maximum requests allowed in the window.
        window_seconds: Length of the sliding window in seconds.

    Returns:
        RateLimitResult indicating whether the request is allowed.
    """
    if redis is None:
        # Redis unavailable — fail open
        logger.warning("Rate limit check skipped (Redis unavailable) | key=%s", key)
        return RateLimitResult(
            allowed=True,
            current_count=0,
            max_requests=max_requests,
            window_seconds=window_seconds,
        )

    now = time.time()
    window_start = now - window_seconds
    # Use a unique member to avoid deduplication by Redis sorted sets.
    # If two requests happen at the exact same timestamp, they still
    # need separate entries.
    member = f"{now}:{uuid.uuid4().hex[:8]}"

    try:
        pipe = redis.pipeline(transaction=True)
        # 1. Remove entries outside the window
        pipe.zremrangebyscore(key, "-inf", window_start)
        # 2. Add current request
        pipe.zadd(key, {member: now})
        # 3. Count requests in window
        pipe.zcard(key)
        # 4. Get the oldest entry (for retry_after calculation)
        pipe.zrange(key, 0, 0, withscores=True)
        # 5. Set TTL so the key auto-cleans when window passes with no requests
        pipe.expire(key, window_seconds)

        results = await pipe.execute()

        current_count: int = results[2]
        allowed = current_count <= max_requests

        retry_after = 0
        if not allowed and results[3]:
            # Oldest entry's score = when it will leave the window
            oldest_score = results[3][0][1]
            retry_after = max(0, int(oldest_score + window_seconds - now) + 1)

        if not allowed:
            logger.info(
                "Rate limit EXCEEDED | key=%s | count=%d/%d | retry_after=%ds",
                key,
                current_count,
                max_requests,
                retry_after,
            )

        return RateLimitResult(
            allowed=allowed,
            current_count=current_count,
            max_requests=max_requests,
            window_seconds=window_seconds,
            retry_after=retry_after,
        )

    except RedisError as e:
        # Fail open — allow the request
        logger.warning(
            "Rate limit check failed (Redis error), allowing request | key=%s | error=%s",
            key,
            str(e),
        )
        return RateLimitResult(
            allowed=True,
            current_count=0,
            max_requests=max_requests,
            window_seconds=window_seconds,
        )
