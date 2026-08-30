"""Embedding service - converts text chunks into vector representations.

Responsibilities:
    - Call OpenAI's embedding API with batched inputs.
    - Handle transient failures with exponential backoff retries.
    - Validate API responses (correct count, correct dimensions).

This service does NOT:
    - Store vectors (that's the pipeline orchestrator's job).
    - Manage chunks (that's the chunking service).
    - Perform search (that's a future retrieval service).

Design decisions:
    - Uses the openai SDK directly (not LangChain's wrapper) for
      full control over batching, retries, and error handling.
    - Batching: groups chunks into batches of EMBEDDING_BATCH_SIZE
      to minimize API calls while staying within limits.
    - Exponential backoff: 1s, 2s, 4s delays between retries.
      Handles 429 (rate limit) and 5xx (server error) gracefully.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import openai

from app.core.config import settings
from app.core.embedding_client import embedding_client

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmbeddingResult:
    """Result of embedding a batch of texts.

    Attributes:
        embeddings: List of vectors, one per input text.
            Each vector is a list of floats with length = EMBEDDING_DIMENSIONS.
        model: The model that produced these embeddings.
        total_tokens: Total tokens consumed across all inputs (for cost tracking).
    """

    embeddings: list[list[float]]
    model: str
    total_tokens: int


class EmbeddingError(Exception):
    """Raised when embedding fails after all retries are exhausted."""

    pass


def embed_texts(
    texts: list[str],
    *,
    model: str | None = None,
    batch_size: int | None = None,
    max_retries: int | None = None,
) -> EmbeddingResult:
    """Embed a list of text strings into vectors using OpenAI's API.

    Handles batching internally: if you pass 50 texts and batch_size=20,
    this makes 3 API calls (20 + 20 + 10) and merges the results.

    Args:
        texts: List of text strings to embed. Cannot be empty.
        model: Embedding model name. Defaults to settings.EMBEDDING_MODEL.
        batch_size: Max texts per API call. Defaults to settings.EMBEDDING_BATCH_SIZE.
        max_retries: Max retry attempts per batch. Defaults to settings.EMBEDDING_MAX_RETRIES.

    Returns:
        EmbeddingResult with all vectors in the same order as input texts.

    Raises:
        EmbeddingError: If any batch fails after all retries.
        ValueError: If texts is empty.
    """
    if not texts:
        raise ValueError("Cannot embed an empty list of texts")

    _model = model or settings.EMBEDDING_MODEL
    _batch_size = batch_size or settings.EMBEDDING_BATCH_SIZE
    _max_retries = max_retries or settings.EMBEDDING_MAX_RETRIES

    all_embeddings: list[list[float]] = []
    total_tokens = 0

    # Split into batches.
    # For a resume with 5 chunks, this is a single batch.
    # For a large document with 200 chunks, this makes 2 batches of 100.
    batches = [texts[i : i + _batch_size] for i in range(0, len(texts), _batch_size)]

    logger.info(
        "Embedding %d texts in %d batches | model=%s | batch_size=%d",
        len(texts),
        len(batches),
        _model,
        _batch_size,
    )

    client = embedding_client

    for batch_idx, batch in enumerate(batches):
        result = _embed_batch_with_retry(
            client=client,
            texts=batch,
            model=_model,
            max_retries=_max_retries,
            batch_idx=batch_idx,
            total_batches=len(batches),
        )

        all_embeddings.extend(result.embeddings)
        total_tokens += result.total_tokens

    # Validate: we should have exactly one embedding per input text.
    if len(all_embeddings) != len(texts):
        raise EmbeddingError(
            f"Embedding count mismatch: expected {len(texts)}, got {len(all_embeddings)}"
        )

    logger.info(
        "Embedding complete | texts=%d | total_tokens=%d | model=%s",
        len(texts),
        total_tokens,
        _model,
    )

    return EmbeddingResult(
        embeddings=all_embeddings,
        model=_model,
        total_tokens=total_tokens,
    )


def _embed_batch_with_retry(
    *,
    client: openai.OpenAI,
    texts: list[str],
    model: str,
    max_retries: int,
    batch_idx: int,
    total_batches: int,
) -> EmbeddingResult:
    """Embed a single batch with exponential backoff retry.

    Retries on:
        - openai.RateLimitError (429) - we're sending too many requests.
        - openai.APIStatusError (5xx) - OpenAI's servers are having issues.
        - openai.APIConnectionError - network issues.

    Does NOT retry on:
        - openai.AuthenticationError (401) - bad API key, retrying won't help.
        - openai.BadRequestError (400) - input is invalid, retrying won't help.
    """
    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            response = client.embeddings.create(
                input=texts,
                model=model,
            )

            embeddings = [item.embedding for item in response.data]

            # Validate dimensions.
            expected_dims = settings.EMBEDDING_DIMENSIONS
            for i, emb in enumerate(embeddings):
                if len(emb) != expected_dims:
                    raise EmbeddingError(
                        f"Dimension mismatch at index {i}: expected {expected_dims}, got {len(emb)}"
                    )

            tokens_used = response.usage.total_tokens if response.usage else 0

            logger.debug(
                "Batch %d/%d embedded | texts=%d | tokens=%d",
                batch_idx + 1,
                total_batches,
                len(texts),
                tokens_used,
            )

            return EmbeddingResult(
                embeddings=embeddings,
                model=model,
                total_tokens=tokens_used,
            )

        except (
            openai.RateLimitError,
            openai.APIConnectionError,
        ) as e:
            last_error = e
            if attempt < max_retries:
                # Exponential backoff: 1s, 2s, 4s, ...
                delay = 2**attempt
                logger.warning(
                    "Embedding batch %d/%d failed (attempt %d/%d), retrying in %ds | error=%s",
                    batch_idx + 1,
                    total_batches,
                    attempt + 1,
                    max_retries + 1,
                    delay,
                    str(e),
                )
                time.sleep(delay)
            else:
                logger.error(
                    "Embedding batch %d/%d failed after %d attempts | error=%s",
                    batch_idx + 1,
                    total_batches,
                    max_retries + 1,
                    str(e),
                )

        except openai.APIStatusError as e:
            # Retry only on server errors (5xx).
            if e.status_code >= 500:
                last_error = e
                if attempt < max_retries:
                    delay = 2**attempt
                    logger.warning(
                        "Embedding batch %d/%d server error (attempt %d/%d), "
                        "retrying in %ds | status=%d",
                        batch_idx + 1,
                        total_batches,
                        attempt + 1,
                        max_retries + 1,
                        delay,
                        e.status_code,
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        "Embedding batch %d/%d failed after %d attempts | status=%d",
                        batch_idx + 1,
                        total_batches,
                        max_retries + 1,
                        e.status_code,
                    )
            else:
                # Client error (4xx other than 429) - don't retry.
                raise EmbeddingError(
                    f"Embedding API error (non-retryable): {e.status_code} - {e.message}"
                ) from e

    raise EmbeddingError(f"Embedding failed after {max_retries + 1} attempts: {last_error}")
