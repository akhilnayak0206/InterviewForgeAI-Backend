"""Embedding pipeline - orchestrates chunk -> embed -> store -> validate.

This is the top-level entry point for converting a processed document
into searchable vector embeddings. It coordinates:

    1. Chunking (text -> overlapping text pieces)
    2. Embedding (text pieces -> vectors via OpenAI API)
    3. Storage (vectors + metadata -> document_chunks table)
    4. Validation (verify counts, dimensions, no nulls)
    5. Status update (document.status -> indexed)

Design decisions:
    - All chunks for a document are inserted in one transaction.
      If embedding fails halfway, no partial chunks are committed.
    - Re-indexing is supported: calling this on an already-indexed
      document deletes old chunks first, then creates fresh ones.
    - The pipeline catches EmbeddingError and sets document.status = failed
      with a descriptive error_message.
    - Token counts are tracked per-chunk for cost reporting.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlmodel import Session, select

from app.core.config import settings
from app.documents.chunk_models import DocumentChunk
from app.documents.chunking import ChunkResult, chunk_text
from app.documents.embedding_service import EmbeddingError, embed_texts
from app.documents.enums import DocumentStatus
from app.documents.models import Document

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PipelineResult:
    """Result of the embedding pipeline for a single document.

    Attributes:
        success: Whether the pipeline completed successfully.
        document_id: The document that was processed.
        chunks_created: Number of chunks created (0 on failure).
        total_tokens: Total tokens consumed for embedding (0 on failure).
        error: Error message if the pipeline failed.
    """

    success: bool
    document_id: uuid.UUID
    chunks_created: int
    total_tokens: int
    error: str | None = None


def embed_document(
    *,
    db: Session,
    document: Document,
) -> PipelineResult:
    """Run the full embedding pipeline for a single document.

    Preconditions:
        - document.status must be 'processed' or 'indexed' (for re-indexing).
        - document.extracted_text must not be empty.

    Flow:
        1. Validate preconditions.
        2. Transition status to 'embedding'.
        3. Delete any existing chunks (for re-indexing).
        4. Chunk the extracted text.
        5. Embed all chunks via OpenAI API.
        6. Store chunks with vectors in the database.
        7. Validate stored chunks.
        8. Transition status to 'indexed'.

    On failure:
        - Status transitions to 'failed'.
        - error_message is set on the document.
        - No chunks are committed.

    Args:
        db: Database session.
        document: The Document to embed. Must have extracted_text.

    Returns:
        PipelineResult with success status and metrics.
    """
    doc_id = document.id

    # -- Step 1: Validate preconditions --
    if document.status not in (DocumentStatus.processed, DocumentStatus.indexed):
        return PipelineResult(
            success=False,
            document_id=doc_id,
            chunks_created=0,
            total_tokens=0,
            error=(
                f"Document status must be 'processed' or 'indexed' for embedding, "
                f"got '{document.status}'"
            ),
        )

    if not document.extracted_text or not document.extracted_text.strip():
        return PipelineResult(
            success=False,
            document_id=doc_id,
            chunks_created=0,
            total_tokens=0,
            error="Document has no extracted text to embed",
        )

    # -- Step 2: Transition to 'embedding' --
    document.status = DocumentStatus.embedding
    document.error_message = None
    db.commit()

    logger.info("Embedding pipeline started | document_id=%s", doc_id)

    try:
        # -- Step 3: Delete existing chunks (for re-indexing) --
        deleted_count = _delete_existing_chunks(db=db, document_id=doc_id)
        if deleted_count > 0:
            logger.info(
                "Deleted %d existing chunks for re-indexing | document_id=%s",
                deleted_count,
                doc_id,
            )

        # -- Step 4: Chunk the text --
        chunks: list[ChunkResult] = chunk_text(document.extracted_text)

        if not chunks:
            raise EmbeddingError("Chunking produced zero chunks")

        logger.info(
            "Chunked document | document_id=%s | chunks=%d",
            doc_id,
            len(chunks),
        )

        # -- Step 5: Embed all chunks --
        chunk_texts = [c.chunk_text for c in chunks]
        embedding_result = embed_texts(chunk_texts)

        # -- Step 6: Store chunks with vectors --
        _store_chunks(
            db=db,
            document=document,
            chunks=chunks,
            embeddings=embedding_result.embeddings,
        )

        # -- Step 7: Validate --
        stored_count = _count_chunks(db=db, document_id=doc_id)
        if stored_count != len(chunks):
            raise EmbeddingError(
                f"Validation failed: expected {len(chunks)} stored chunks, found {stored_count}"
            )

        # -- Step 8: Transition to 'indexed' --
        document.status = DocumentStatus.indexed
        document.error_message = None
        db.commit()

        logger.info(
            "Embedding pipeline complete | document_id=%s | chunks=%d | tokens=%d",
            doc_id,
            len(chunks),
            embedding_result.total_tokens,
        )

        return PipelineResult(
            success=True,
            document_id=doc_id,
            chunks_created=len(chunks),
            total_tokens=embedding_result.total_tokens,
        )

    except (EmbeddingError, Exception) as e:
        # Roll back any uncommitted changes from this attempt.
        db.rollback()

        # Refresh the document to get a clean state after rollback.
        db.refresh(document)

        # Set failure status.
        document.status = DocumentStatus.failed
        document.error_message = f"Embedding failed: {str(e)}"
        db.commit()

        logger.error(
            "Embedding pipeline failed | document_id=%s | error=%s",
            doc_id,
            str(e),
        )

        return PipelineResult(
            success=False,
            document_id=doc_id,
            chunks_created=0,
            total_tokens=0,
            error=str(e),
        )


def _delete_existing_chunks(*, db: Session, document_id: uuid.UUID) -> int:
    """Delete all chunks for a document (used during re-indexing).

    Returns the number of chunks deleted.
    """
    stmt = select(DocumentChunk).where(DocumentChunk.document_id == document_id)
    existing = db.exec(stmt).all()

    count = len(existing)
    for chunk in existing:
        db.delete(chunk)

    if count > 0:
        db.flush()

    return count


def _store_chunks(
    *,
    db: Session,
    document: Document,
    chunks: list[ChunkResult],
    embeddings: list[list[float]],
) -> None:
    """Create DocumentChunk records with their embeddings.

    All chunks are added to the session but NOT committed -
    the caller commits after validation.

    Denormalized fields (user_id, session_id, document_type) are copied
    from the parent Document to avoid JOINs during vector search.
    """
    for chunk, embedding in zip(chunks, embeddings):
        db_chunk = DocumentChunk(
            document_id=document.id,
            user_id=document.user_id,
            session_id=document.session_id,
            document_type=document.document_type,
            chunk_index=chunk.chunk_index,
            chunk_text=chunk.chunk_text,
            embedding=embedding,
            embedding_model=settings.EMBEDDING_MODEL,
            embedding_version=settings.EMBEDDING_VERSION,
            token_count=chunk.token_count,
        )
        db.add(db_chunk)

    # Flush to DB (within the current transaction) so we can validate.
    db.flush()


def _count_chunks(*, db: Session, document_id: uuid.UUID) -> int:
    """Count the number of chunks stored for a document.

    Used for post-storage validation.
    """
    from sqlmodel import func

    stmt = select(func.count()).where(DocumentChunk.document_id == document_id)
    return db.exec(stmt).one()
