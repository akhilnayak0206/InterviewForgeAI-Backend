from openai import AsyncOpenAI, OpenAI

from app.core.config import settings


def get_embedding_client() -> OpenAI:
    """
    Returns an OpenAI-compatible client configured for OpenRouter.
    Uses OpenRouter API key if available, falls back to OpenAI API key.
    """
    api_key = settings.OPENROUTER_API_KEY or settings.OPENAI_API_KEY
    base_url = settings.OPENROUTER_BASE_URL

    return OpenAI(api_key=api_key, base_url=base_url)


def get_async_embedding_client() -> AsyncOpenAI:
    """
    Returns an async OpenAI-compatible client configured for OpenRouter.
    Uses OpenRouter API key if available, falls back to OpenAI API key.
    """
    api_key = settings.OPENROUTER_API_KEY or settings.OPENAI_API_KEY
    base_url = settings.OPENROUTER_BASE_URL

    return AsyncOpenAI(api_key=api_key, base_url=base_url)


# Lazy-initialized clients for direct use in modules.
# These are created on first access and reused thereafter.
_embedding_client: OpenAI | None = None
_async_embedding_client: AsyncOpenAI | None = None


def _get_or_create_embedding_client() -> OpenAI:
    """Get or create the singleton embedding client."""
    global _embedding_client
    if _embedding_client is None:
        _embedding_client = get_embedding_client()
    return _embedding_client


def _get_or_create_async_embedding_client() -> AsyncOpenAI:
    """Get or create the singleton async embedding client."""
    global _async_embedding_client
    if _async_embedding_client is None:
        _async_embedding_client = get_async_embedding_client()
    return _async_embedding_client


# Export singleton instances for direct import.
embedding_client = _get_or_create_embedding_client()
async_embedding_client = _get_or_create_async_embedding_client()
