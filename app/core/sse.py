"""Helpers for Server-Sent Event (SSE) streaming endpoints."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from openai import APIConnectionError, APIStatusError, RateLimitError

logger = logging.getLogger(__name__)


def sse_event(event_type: str, payload: dict[str, Any]) -> str:
    """Build a single SSE event string."""
    return f"data: {json.dumps({'type': event_type, **payload})}\n\n"


def sse_error(detail: str) -> str:
    """Build an SSE error event."""
    return sse_event("error", {"detail": detail})


async def wrap_stream_with_sse_errors(
    stream: AsyncGenerator[str, None],
    *,
    user_id: Any | None = None,
) -> AsyncGenerator[str, None]:
    """Wrap an async stream and convert OpenAI errors into SSE error events.

    Use this for any streaming endpoint that calls a third-party LLM so
    errors are delivered to the client over the already-open SSE connection
    instead of silently failing.
    """
    try:
        async for event in stream:
            yield event

    except RateLimitError:
        logger.warning("OpenAI rate limit hit during stream | user=%s", user_id)
        yield sse_error("AI service is temporarily overloaded. Please try again.")

    except APIConnectionError:
        logger.error("OpenAI connection lost during stream")
        yield sse_error("Lost connection to AI service.")

    except APIStatusError as exc:
        logger.error(
            "OpenAI API error during stream | status=%d | message=%s",
            exc.status_code,
            exc.message,
        )
        yield sse_error("AI service returned an error.")

    except Exception:
        # Catch-all for other providers (Anthropic, etc.) and setup errors.
        # CancelledError is a BaseException, so it is NOT caught here.
        logger.exception("Unexpected error during stream | user=%s", user_id)
        yield sse_error("AI service returned an error.")