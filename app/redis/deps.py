"""FastAPI dependencies for Redis features.

These dependencies wire Redis into the request lifecycle using
FastAPI's Depends() system — the same pattern used for database
sessions (get_db) and authentication (get_current_active_user).

Usage in routes:

    @router.post("/chat")
    async def chat(
        redis: Redis | None = Depends(get_redis),
    ):
        # redis is the shared client, or None if unavailable.
        ...

    @router.post("/chat")
    async def chat(
        _: None = Depends(rate_limit_chat),
        current_user: User = Depends(get_current_active_user),
    ):
        # rate_limit_chat raises 429 if limit exceeded.
        ...
"""

from __future__ import annotations

import logging

from fastapi import Depends, HTTPException, Request, status
from redis.asyncio import Redis

from app.core.config import settings
from app.core.deps import get_current_active_user
from app.models.user import User
from app.redis.client import get_redis_client
from app.redis.keys import rate_limit_ip_key, rate_limit_key
from app.redis.rate_limit import check_rate_limit

logger = logging.getLogger(__name__)


async def get_redis() -> Redis | None:
    """Dependency that provides the shared Redis client.

    Returns None if Redis is unavailable. All callers must handle
    None gracefully (which cache.py, rate_limit.py, and locks.py
    already do).
    """
    return get_redis_client()


async def rate_limit_chat(
    current_user: User = Depends(get_current_active_user),
    redis: Redis | None = Depends(get_redis),
) -> None:
    """Rate limit for chat/LLM endpoints.

    20 requests per minute per user. This prevents a single user
    from burning through LLM API credits.

    On limit exceeded: raises HTTP 429 with Retry-After header.
    On Redis failure: fails open (allows request).
    """
    result = await check_rate_limit(
        redis,
        rate_limit_key(current_user.id, "chat"),
        max_requests=settings.RATE_LIMIT_CHAT_MAX,
        window_seconds=settings.RATE_LIMIT_CHAT_WINDOW,
    )

    if not result.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Try again in {result.retry_after} seconds.",
            headers={"Retry-After": str(result.retry_after)},
        )


async def rate_limit_embed(
    current_user: User = Depends(get_current_active_user),
    redis: Redis | None = Depends(get_redis),
) -> None:
    """Rate limit for embedding endpoints.

    5 requests per minute per user. Embedding is expensive (API calls
    + vector storage).
    """
    result = await check_rate_limit(
        redis,
        rate_limit_key(current_user.id, "embed"),
        max_requests=settings.RATE_LIMIT_EMBED_MAX,
        window_seconds=settings.RATE_LIMIT_EMBED_WINDOW,
    )

    if not result.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Try again in {result.retry_after} seconds.",
            headers={"Retry-After": str(result.retry_after)},
        )


async def rate_limit_auth(
    request: Request,
    redis: Redis | None = Depends(get_redis),
) -> None:
    """Rate limit for authentication endpoints (login, register).

    10 requests per minute per IP address. Prevents brute-force
    login attempts.

    Uses IP instead of user_id because the user isn't authenticated
    yet on login/register endpoints.
    """
    client_ip = request.client.host if request.client else "unknown"

    result = await check_rate_limit(
        redis,
        rate_limit_ip_key(client_ip, "auth"),
        max_requests=settings.RATE_LIMIT_AUTH_MAX,
        window_seconds=settings.RATE_LIMIT_AUTH_WINDOW,
    )

    if not result.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many attempts. Try again in {result.retry_after} seconds.",
            headers={"Retry-After": str(result.retry_after)},
        )
