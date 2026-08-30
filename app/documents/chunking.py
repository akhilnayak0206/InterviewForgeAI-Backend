from __future__ import annotations

import logging
from dataclasses import dataclass

import tiktoken
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import settings

logger = logging.getLogger(__name__)

# Cache the tokenizer - it's expensive to initialize.
# cl100k_base is the tokenizer used by text-embedding-3-small/large and GPT-4.
_tokenizer: tiktoken.Encoding | None = None


def _get_tokenizer() -> tiktoken.Encoding:
    """Lazily load and cache the tokenizer.

    tiktoken.get_encoding() downloads the tokenizer data on first call.
    Caching avoids repeated downloads and initialization overhead.
    """
    global _tokenizer
    if _tokenizer is None:
        _tokenizer = tiktoken.get_encoding("cl100k_base")
    return _tokenizer


def count_tokens(text: str) -> int:
    """Count the number of tokens in a text string.

    Uses the same tokenizer that OpenAI's embedding models use (cl100k_base).
    This gives an exact token count, not an estimate.

    Args:
        text: The text to count tokens for.

    Returns:
        Number of tokens.
    """
    tokenizer = _get_tokenizer()
    return len(tokenizer.encode(text))


@dataclass(frozen=True)
class ChunkResult:
    """A single chunk produced by the text splitter.

    Attributes:
        chunk_index: Position within the document (0-indexed).
        chunk_text: The text content of this chunk.
        token_count: Number of tokens (cl100k_base tokenizer).
    """

    chunk_index: int
    chunk_text: str
    token_count: int


def chunk_text(
    text: str,
    *,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> list[ChunkResult]:
    """Split text into overlapping chunks suitable for embedding.

    Uses RecursiveCharacterTextSplitter from LangChain, which tries
    to split on natural boundaries (paragraphs, lines, sentences)
    before falling back to character-level splitting.

    Args:
        text: The normalized text to split (from Document.extracted_text).
        chunk_size: Target chunk size in characters. Defaults to settings.CHUNK_SIZE.
        chunk_overlap: Overlap between chunks in characters. Defaults to settings.CHUNK_OVERLAP.

    Returns:
        List of ChunkResult objects, ordered by chunk_index.
        Empty list if text is empty or whitespace-only.

    Why these defaults matter:
        - chunk_size=1600 chars is ~400 tokens. Large enough to contain
          a resume section (e.g., one job entry), small enough for
          precise retrieval.
        - chunk_overlap=200 chars is ~12.5% of chunk size. Ensures
          sentences that span chunk boundaries appear in both chunks.
    """
    if not text or not text.strip():
        logger.warning("chunk_text called with empty text")
        return []

    size = chunk_size or settings.CHUNK_SIZE
    overlap = chunk_overlap or settings.CHUNK_OVERLAP

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=size,
        chunk_overlap=overlap,
        # Separators tried in order. This is the default set,
        # listed explicitly for clarity.
        separators=["\n\n", "\n", ". ", " ", ""],
        # Keep the separator with the preceding chunk.
        # "Experience at Google.\nEducation" splits as:
        #   ["Experience at Google.", "Education"]
        # not ["Experience at Google", ".\nEducation"]
        keep_separator=False,
        # Do not strip whitespace from chunks.
        # The text is already normalized by text_processing.py.
        strip_whitespace=True,
    )

    raw_chunks: list[str] = splitter.split_text(text)

    results: list[ChunkResult] = []
    for index, chunk in enumerate(raw_chunks):
        token_count = count_tokens(chunk)
        results.append(
            ChunkResult(
                chunk_index=index,
                chunk_text=chunk,
                token_count=token_count,
            )
        )

    total_tokens = sum(r.token_count for r in results)
    logger.info(
        "Chunked text | chunks=%d | total_tokens=%d | avg_tokens=%d | chunk_size=%d | overlap=%d",
        len(results),
        total_tokens,
        total_tokens // len(results) if results else 0,
        size,
        overlap,
    )

    return results
