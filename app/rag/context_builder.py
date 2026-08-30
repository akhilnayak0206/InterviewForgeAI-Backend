"""Context builder - transforms retrieved chunks into prompt-ready strings.

Takes raw RetrievedChunk objects from the retriever and produces
formatted context strings ready for injection into LLM prompts.

Design decisions:
    - Chunks are joined with clear separators so the LLM can distinguish
      between different pieces of information.
    - Token budget prevents context from exceeding a configurable limit.
      Chunks are added in order until the budget is exhausted.
    - Returns empty string (not None) when no context is available,
      so prompts can safely use the value without null checks.
    - Ordering: chunks arrive pre-sorted by similarity from the retriever.
      The builder preserves that order (most relevant first).
"""

from __future__ import annotations

import logging

from app.rag.retriever import RetrievedChunk

logger = logging.getLogger(__name__)

# -- Defaults --
# Maximum total tokens to include in context.
# ~3000 tokens = 7-8 chunks of ~400 tokens each.
# Leaves plenty of room for the rest of the prompt + LLM output
# within the model's context window.
DEFAULT_MAX_CONTEXT_TOKENS = 3000

# Separator between chunks in the formatted output.
# Clear visual boundary so the LLM doesn't blend adjacent chunks.
CHUNK_SEPARATOR = "\n---\n"


def build_context(
    chunks: list[RetrievedChunk],
    *,
    max_tokens: int = DEFAULT_MAX_CONTEXT_TOKENS,
) -> str:
    """Build a prompt-ready context string from retrieved chunks.

    Chunks are included in order (the retriever already sorted them
    by relevance). Stops adding chunks when the token budget is exceeded.

    Args:
        chunks: Retrieved chunks, pre-sorted by relevance.
        max_tokens: Maximum total tokens to include.

    Returns:
        Formatted context string. Empty string if no chunks fit.

    Example output:
        "Built REST APIs using FastAPI with PostgreSQL at Company X...
        ---
        Led migration from Django to FastAPI, reducing latency by 40%...
        ---
        Implemented async task queue with Celery for PDF processing..."
    """
    if not chunks:
        return ""

    selected: list[str] = []
    total_tokens = 0

    for chunk in chunks:
        if total_tokens + chunk.token_count > max_tokens:
            # Budget exhausted - stop adding chunks.
            # We don't split a chunk in half; it either fits or it doesn't.
            logger.debug(
                "Token budget reached | used=%d | limit=%d | chunks_included=%d",
                total_tokens,
                max_tokens,
                len(selected),
            )
            break

        selected.append(chunk.chunk_text)
        total_tokens += chunk.token_count

    if not selected:
        # Edge case: first chunk alone exceeds the budget.
        # Include it anyway - some context is better than none.
        selected.append(chunks[0].chunk_text)
        total_tokens = chunks[0].token_count

    context = CHUNK_SEPARATOR.join(selected)

    logger.info(
        "Built context | chunks=%d/%d | tokens=%d | max=%d",
        len(selected),
        len(chunks),
        total_tokens,
        max_tokens,
    )

    return context


def build_resume_and_jd_context(
    *,
    resume_chunks: list[RetrievedChunk],
    jd_chunks: list[RetrievedChunk],
    max_resume_tokens: int = 2000,
    max_jd_tokens: int = 1500,
) -> tuple[str, str]:
    """Build separate context strings for resume and job description.

    Convenience wrapper that calls build_context twice with
    independent token budgets.

    Args:
        resume_chunks: Retrieved resume chunks.
        jd_chunks: Retrieved job description chunks.
        max_resume_tokens: Token budget for resume context.
        max_jd_tokens: Token budget for JD context.

    Returns:
        Tuple of (resume_context, jd_context).
        Either or both may be empty strings.
    """
    resume_context = build_context(resume_chunks, max_tokens=max_resume_tokens)
    jd_context = build_context(jd_chunks, max_tokens=max_jd_tokens)

    return resume_context, jd_context
