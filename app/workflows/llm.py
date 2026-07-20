"""
Workflow LLM Factory
=====================

Provides a single function `get_workflow_llm()` that returns a LangChain
BaseChatModel configured from application settings.

WHY THIS EXISTS:
    Workflow nodes should not know which LLM provider is being used.
    They call `get_workflow_llm()` and get a model back. When you change
    LLM_PROVIDER in .env, no node code changes.

    This mirrors the existing `app/core/providers.py` pattern but returns
    a LangChain-compatible model instead of a raw streaming provider.

PROVIDER SUPPORT:
    - "openai"    → ChatOpenAI (also works for Groq, OpenRouter, etc.)
    - "anthropic" → ChatAnthropic (requires `langchain-anthropic` package)
"""

from __future__ import annotations

import logging
from functools import lru_cache

from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic

from app.core.config import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_workflow_llm():
    """
    Return a LangChain chat model configured from application settings.

    Cached so the same instance is reused across all nodes and requests.
    Thread-safe — LangChain models use httpx connection pooling internally.
    """

    provider = settings.LLM_PROVIDER.lower()

    if provider == "openai":
        llm = ChatOpenAI(
            model=settings.OPENAI_MODEL,
            api_key=settings.OPENAI_API_KEY,
            temperature=settings.OPENAI_TEMPERATURE,
            max_tokens=settings.OPENAI_MAX_TOKENS,
            base_url="https://api.groq.com/openai/v1",
        )
        logger.info(
            "Workflow LLM initialized | provider=openai | model=%s",
            settings.OPENAI_MODEL,
        )
        return llm

    if provider == "anthropic":
        if not settings.ANTHROPIC_API_KEY:
            raise ValueError(
                "ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic"
            )

        llm = ChatAnthropic(
            model=settings.ANTHROPIC_MODEL,
            api_key=settings.ANTHROPIC_API_KEY,
            temperature=settings.OPENAI_TEMPERATURE,
            max_tokens=settings.OPENAI_MAX_TOKENS,
        )
        logger.info(
            "Workflow LLM initialized | provider=anthropic | model=%s",
            settings.ANTHROPIC_MODEL,
        )
        return llm

    raise ValueError(
        f"Unsupported LLM_PROVIDER: '{settings.LLM_PROVIDER}'. "
        f"Supported: 'openai', 'anthropic'"
    )
