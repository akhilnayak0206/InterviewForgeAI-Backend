"""Provider abstraction for LLM streaming.

This module decouples the chat service from any specific LLM SDK.
Switching providers only requires changing `LLM_PROVIDER` in settings.

Supported providers:
    - openai      (OpenAI, Groq, or any OpenAI-compatible API)
    - anthropic   (Anthropic Claude)

To add a new provider:
    1. Create a class inheriting from `BaseProvider`.
    2. Implement the `stream` async generator.
    3. Register it in `get_provider()`.
"""

from __future__ import annotations

import logging
from abc import ABC
from collections.abc import AsyncGenerator

from app.core.config import settings
from app.core.openai_client import async_openai_client

logger = logging.getLogger(__name__)


class BaseProvider(ABC):
    """Abstract base for LLM streaming providers.

    Each provider yields plain text tokens as strings. The caller
    (`ai.py`) is responsible for wrapping those tokens into SSE events.
    """

    async def stream(
        self,
        messages: list[dict[str, str]],
    ) -> AsyncGenerator[str, None]:
        """Yield response tokens one at a time."""
        yield ""


class OpenAIProvider(BaseProvider):
    """OpenAI-compatible streaming provider.

    Works for OpenAI, Groq, OpenRouter, and any other service that
    implements the OpenAI chat completions API.
    """

    async def stream(
        self,
        messages: list[dict[str, str]],
    ) -> AsyncGenerator[str, None]:
        response_stream = await async_openai_client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=messages,
            max_tokens=settings.OPENAI_MAX_TOKENS,
            temperature=settings.OPENAI_TEMPERATURE,
            stream=True,
        )

        async for chunk in response_stream:
            if not chunk.choices:
                continue

            choice = chunk.choices[0]
            token = choice.delta.content

            if token:
                yield token


class AnthropicProvider(BaseProvider):
    """Anthropic Claude streaming provider.

    Install the Anthropic SDK to use this provider:
        pip install anthropic

    Set in your `.env`:
        LLM_PROVIDER=anthropic
        ANTHROPIC_API_KEY=your_key
    """

    def __init__(self) -> None:
        try:
            import anthropic
        except ImportError as exc:
            raise ImportError(
                "Anthropic provider requires the `anthropic` package. "
                "Install it with: pip install anthropic"
            ) from exc

        if not settings.ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic")

        self._client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    async def stream(
        self,
        messages: list[dict[str, str]],
    ) -> AsyncGenerator[str, None]:
        # Anthropic expects the system prompt as a separate parameter.
        system_content: str | None = None
        chat_messages: list[dict[str, str]] = []

        for message in messages:
            if message.get("role") == "system":
                system_content = message.get("content")
            else:
                chat_messages.append(message)

        response_stream = await self._client.messages.create(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=settings.OPENAI_MAX_TOKENS,
            temperature=settings.OPENAI_TEMPERATURE,
            system=system_content,
            messages=chat_messages,  # type: ignore[arg-type]
            stream=True,
        )

        async for event in response_stream:
            if event.type == "content_block_delta":
                # Prefer text deltas; ignore input_json deltas (tool use).
                text = getattr(event.delta, "text", None)
                if text:
                    yield text


def get_provider() -> BaseProvider:
    """Return the configured provider instance."""
    provider = settings.LLM_PROVIDER.lower()

    if provider == "openai":
        return OpenAIProvider()
    if provider == "anthropic":
        return AnthropicProvider()

    raise ValueError(f"Unsupported LLM_PROVIDER: {settings.LLM_PROVIDER}")