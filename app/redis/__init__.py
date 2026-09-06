"""Redis infrastructure — caching, rate limiting, distributed locks.

This package provides application-level Redis functionality SEPARATE
from the ARQ job queue (app/jobs/queue.py). ARQ uses Redis as a queue
broker. This package uses Redis as:

    - Cache store (cache-aside pattern)
    - Rate limiter (sliding window)
    - Distributed lock coordinator

Both share the same Redis server but use different key namespaces
to avoid collisions. ARQ uses its own internal key format (arq:*).
Our keys use explicit namespaces: cache:*, ratelimit:*, lock:*.

All functions handle Redis failures gracefully — the application
continues working (slower, without limits) if Redis goes down.
"""

from app.redis.cache import cache_delete, cache_get_or_set
from app.redis.client import close_redis_pool, get_redis_client, init_redis_pool
from app.redis.keys import cache_session_key, lock_key, rate_limit_key
from app.redis.locks import acquire_lock, release_lock
from app.redis.rate_limit import RateLimitResult, check_rate_limit

__all__ = [
    "cache_delete",
    "cache_get_or_set",
    "close_redis_pool",
    "get_redis_client",
    "init_redis_pool",
    "cache_session_key",
    "lock_key",
    "rate_limit_key",
    "acquire_lock",
    "release_lock",
    "RateLimitResult",
    "check_rate_limit",
]
