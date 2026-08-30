"""Retriever - vector search with metadata filtering and ranking.

This is the core retrieval component of the RAG pipeline. It:
    1. Embeds a query string into a vector (same model as stored chunks).
    2. Executes a filtered vector search against pgvector.
    3. Returns ranked results with similarity scores.

Design decisions:
    - user_id is REQUIRED on every call. This is a security constraint,
      not an optional filter. User A must never see User B's chunks.
    - Similarity threshold filters out low-quality matches. A chunk with
      0.15 cosine similarity is noise, not context.
    - Returns dataclass results (RetrievedChunk) so callers don't depend
      on ORM internals. The retriever is a clean boundary.
    - Query embedding uses the same model/version as stored chunks.
      Comparing vectors from different models produces garbage.
    - For the "retrieve all context" pattern (no specific query), we use
      a lightweight approach: retrieve by document type without a query
      vector, ordered by chunk_index to preserve document structure.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlmodel import Session, col, select

from app.documents.chunk_models import DocumentChunk
from app.documents.embedding_service import embed_texts
from app.documents.enums import DocumentType

logger = logging.getLogger(__name__)

# -- Default retrieval parameters --
DEFAULT_TOP_K = 5
DEFAULT_SIMILARITY_THRESHOLD = 0.3


@dataclass(frozen=True)
class RetrievedChunk:
    """A chunk returned by the retriever with its similarity score.

    Attributes:
        chunk_id: Unique ID of the chunk.
        document_id: Parent document ID.
        document_type: "resume" or "job_description".
        chunk_index: Position within the original document.
        chunk_text: The actual text content.
        similarity: Cosine similarity score (0.0 to 1.0). Higher = more relevant.
        token_count: Number of tokens in this chunk.
    """

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_type: str
    chunk_index: int
    chunk_text: str
    similarity: float
    token_count: int


def retrieve_by_query(
    *,
    db: Session,
    query: str,
    user_id: uuid.UUID,
    document_type: DocumentType | None = None,
    session_id: uuid.UUID | None = None,
    top_k: int = DEFAULT_TOP_K,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> list[RetrievedChunk]:
    """Retrieve chunks most similar to a query string.

    Flow:
        1. Embed the query using the same model as stored chunks.
        2. Execute filtered vector search via pgvector.
        3. Filter by similarity threshold.
        4. Return top-K results ordered by similarity (descending).

    Args:
        db: Database session.
        query: Text to search for (will be embedded).
        user_id: REQUIRED. Only retrieve this user's chunks.
        document_type: Optional filter - "resume" or "job_description".
        session_id: Optional filter - only chunks linked to this session.
        top_k: Maximum number of chunks to return.
        similarity_threshold: Minimum cosine similarity (0.0-1.0).

    Returns:
        List of RetrievedChunk, ordered by similarity (highest first).
        Empty list if no chunks meet the threshold.
    """
    # Step 1: Embed the query.
    embedding_result = embed_texts([query])
    query_vector = embedding_result.embeddings[0]

    # Step 2: Vector search.
    return _vector_search(
        db=db,
        query_vector=query_vector,
        user_id=user_id,
        document_type=document_type,
        session_id=session_id,
        top_k=top_k,
        similarity_threshold=similarity_threshold,
    )


def retrieve_by_document_type(
    *,
    db: Session,
    user_id: uuid.UUID,
    document_type: DocumentType,
    session_id: uuid.UUID | None = None,
    top_k: int = DEFAULT_TOP_K,
) -> list[RetrievedChunk]:
    """Retrieve all chunks for a user filtered by document type.

    Unlike retrieve_by_query, this does NOT use semantic search.
    It returns chunks ordered by chunk_index (document order).

    This is useful when you want ALL resume chunks or ALL JD chunks
    without a specific query - e.g., on the first turn when you want
    to inject full document context into the prompt.

    Args:
        db: Database session.
        user_id: REQUIRED. Only retrieve this user's chunks.
        document_type: "resume" or "job_description".
        session_id: Optional - only chunks linked to this session.
        top_k: Maximum chunks to return.

    Returns:
        List of RetrievedChunk ordered by chunk_index (document order).
        Similarity is set to 1.0 since no query-based ranking is applied.
    """
    stmt = (
        select(DocumentChunk)
        .where(
            DocumentChunk.user_id == user_id,
            DocumentChunk.document_type == document_type.value,
        )
        .order_by(col(DocumentChunk.chunk_index))
        .limit(top_k)
    )

    if session_id is not None:
        stmt = stmt.where(DocumentChunk.session_id == session_id)

    chunks = db.exec(stmt).all()

    results = [
        RetrievedChunk(
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            document_type=chunk.document_type,
            chunk_index=chunk.chunk_index,
            chunk_text=chunk.chunk_text,
            similarity=1.0,  # no query-based ranking
            token_count=chunk.token_count,
        )
        for chunk in chunks
    ]

    logger.info(
        "Retrieved %d chunks | user=%s | type=%s | method=by_document_type",
        len(results),
        user_id,
        document_type.value,
    )

    return results


def _vector_search(
    *,
    db: Session,
    query_vector: list[float],
    user_id: uuid.UUID,
    document_type: DocumentType | None,
    session_id: uuid.UUID | None,
    top_k: int,
    similarity_threshold: float,
) -> list[RetrievedChunk]:
    """Execute a filtered vector search against pgvector.

    Uses raw SQL because SQLModel/SQLAlchemy don't have native
    support for pgvector's <=> operator in a clean way.

    The query:
        1. Computes cosine similarity: 1 - (embedding <=> query_vector)
        2. Filters by user_id (mandatory) + optional filters
        3. Filters by similarity threshold
        4. Orders by similarity descending
        5. Limits to top_k results

    Why raw SQL:
        pgvector's cosine distance operator (<=>) isn't part of
        SQLAlchemy's standard operator set. Using text() is cleaner
        than fighting with custom operators for a single query pattern.
    """
    # Build the query dynamically based on filters.
    where_clauses = ["user_id = :user_id"]
    params: dict = {
        "user_id": str(user_id),
        "query_vector": str(query_vector),
        "threshold": similarity_threshold,
        "top_k": top_k,
    }

    if document_type is not None:
        where_clauses.append("document_type = :document_type")
        params["document_type"] = document_type.value

    if session_id is not None:
        where_clauses.append("session_id = :session_id")
        params["session_id"] = str(session_id)

    where_sql = " AND ".join(where_clauses)

    sql = text(f"""
        SELECT
            id,
            document_id,
            document_type,
            chunk_index,
            chunk_text,
            token_count,
            1 - (embedding <=> :query_vector::vector) AS similarity
        FROM document_chunks
        WHERE {where_sql}
          AND 1 - (embedding <=> :query_vector::vector) >= :threshold
        ORDER BY embedding <=> :query_vector::vector
        LIMIT :top_k
    """)

    rows = db.execute(sql, params=params).all()

    results = [
        RetrievedChunk(
            chunk_id=row.id,
            document_id=row.document_id,
            document_type=row.document_type,
            chunk_index=row.chunk_index,
            chunk_text=row.chunk_text,
            similarity=float(row.similarity),
            token_count=row.token_count,
        )
        for row in rows
    ]

    logger.info(
        "Vector search | user=%s | type=%s | results=%d | top_similarity=%.3f | "
        "threshold=%.2f | top_k=%d",
        user_id,
        document_type.value if document_type else "all",
        len(results),
        results[0].similarity if results else 0.0,
        similarity_threshold,
        top_k,
    )

    return results
