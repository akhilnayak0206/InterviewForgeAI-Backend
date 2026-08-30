"""DocumentChunk model - stores embedded text chunks for vector search.

Each Document is split into overlapping chunks, each independently embedded
and stored with its vector representation. This table is the foundation
of the semantic search pipeline.

Design decisions:
    - user_id and session_id are denormalized from Document to avoid JOINs
      during vector search queries (WHERE user_id = X ORDER BY embedding <=> v).
    - embedding_model and embedding_version enable safe model upgrades:
      you cannot compare vectors from different models.
    - metadata_ (JSON) provides flexible extensibility without schema migrations.
"""

from __future__ import annotations

import uuid
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlmodel import Field

from app.documents.enums import DocumentType
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin

# -- Constants --
# Dimension count for the embedding model we use (text-embedding-3-small).
# Changing models means changing this value AND re-embedding all chunks.
EMBEDDING_DIMENSIONS = 1536


class DocumentChunk(UUIDPrimaryKeyMixin, TimestampMixin, table=True):
    """A single embedded chunk of a document.

    One Document produces many DocumentChunks.
    Each chunk has its own vector embedding for semantic search.
    """

    __tablename__ = "document_chunks"

    # -- Parent Reference --
    # Links to the source Document. CASCADE delete is NOT used here;
    # chunk cleanup is handled explicitly in the embedding service
    # so we can log and track what was removed.
    document_id: uuid.UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("documents.id"),
            nullable=False,
            index=True,
        )
    )

    # -- Denormalized Filter Columns --
    # Copied from the parent Document at chunk creation time.
    # Avoids JOIN during vector search (the hot path).
    user_id: uuid.UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("users.id"),
            nullable=False,
            index=True,
        )
    )

    session_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("interview_sessions.id"),
            nullable=True,
            index=True,
        ),
    )

    document_type: DocumentType = Field(
        sa_column=Column(String(length=32), nullable=False, index=True)
    )

    # -- Chunk Content --
    # Position of this chunk within the document (0-indexed).
    # Enables reconstructing document order from retrieved chunks.
    chunk_index: int = Field(sa_column=Column(Integer, nullable=False))

    # The actual text content of this chunk.
    # Stored alongside the vector so retrieval doesn't require
    # a second lookup or re-splitting the original document.
    chunk_text: str = Field(sa_column=Column(Text, nullable=False))

    # -- Embedding --
    # The vector representation of chunk_text.
    # pgvector's Vector type stores a fixed-length float array.
    # 1536 dimensions = text-embedding-3-small.
    embedding: Any = Field(
        sa_column=Column(
            Vector(EMBEDDING_DIMENSIONS),
            nullable=False,
        )
    )

    # -- Versioning --
    # Which model produced this embedding. Critical for:
    # 1. Knowing which chunks need re-embedding after model upgrade
    # 2. Ensuring you only compare vectors from the same model
    embedding_model: str = Field(sa_column=Column(String(length=128), nullable=False))

    # Tracks changes to chunking strategy, preprocessing, or other
    # pipeline parameters that affect the embedding even with the same model.
    # Increment this when you change chunk_size, overlap, or normalization.
    embedding_version: str = Field(
        default="v1",
        sa_column=Column(String(length=32), nullable=False),
    )

    # Number of tokens in this chunk (as counted by the embedding model's tokenizer).
    # Used for cost tracking and validating chunks stay within model limits.
    token_count: int = Field(sa_column=Column(Integer, nullable=False))

    # -- Flexible Metadata --
    # JSON field for anything else: source page number, section header,
    # confidence scores, etc. Future-proofing without schema migrations.
    # Named metadata_ to avoid collision with SQLModel's internal .metadata attribute.
    metadata_: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column("metadata", JSON, nullable=True),
    )

    # -- Table-Level Indexes --
    # The HNSW vector index is created in a separate Alembic migration
    # because it requires the pgvector extension and special syntax.
    # Standard B-tree indexes are defined inline on columns above.
    __table_args__ = (
        # Composite index for the most common query pattern:
        # "find chunks for this user with this document type"
        # This covers the WHERE clause of vector search queries.
        Index(
            "ix_document_chunks_user_type",
            "user_id",
            "document_type",
        ),
        # Composite index for document-scoped operations:
        # "get all chunks for this document in order"
        # Used during re-indexing and chunk cleanup.
        Index(
            "ix_document_chunks_document_order",
            "document_id",
            "chunk_index",
        ),
    )
