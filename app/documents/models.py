
import uuid
from enum import Enum
from typing import TYPE_CHECKING, Optional

from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from sqlalchemy import Column, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlmodel import Field, Relationship

if TYPE_CHECKING:
    from app.models.session import InterviewSession
    from app.models.user import User


class DocumentType(str, Enum):
    """What kind of document was uploaded.

    This matters because processing logic may differ:
    - Resumes have structured sections (Experience, Education, Skills)
    - Job descriptions have different structures (Requirements, Responsibilities)
    """

    resume = "resume"
    job_description = "job_description"


class DocumentStatus(str, Enum):
    """Processing state machine for a document.

    Transitions:
        uploading  -> uploaded    (file stored successfully)
        uploaded   -> extracting  (extraction started)
        extracting -> processed   (text extracted and cleaned)
        extracting -> failed      (extraction error)
        uploaded   -> failed      (validation error discovered post-upload)

    Any state can transition to failed. Only processed is a terminal success.
    """

    uploading = "uploading"
    uploaded = "uploaded"
    extracting = "extracting"
    processed = "processed"
    failed = "failed"


class Document(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, table=True):
    __tablename__ = "documents"

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

    original_filename: str = Field(sa_column=Column(String(length=512), nullable=False))

    storage_filename: str = Field(sa_column=Column(String(length=256), nullable=False))

    mime_type: str = Field(sa_column=Column(String(length=128), nullable=False))

    file_size: int = Field(sa_column=Column(Integer, nullable=False))

    storage_path: str = Field(sa_column=Column(String(length=1024), nullable=False))

    # — Processing State —
    # Where this document is in the ingestion pipeline.
    status: DocumentStatus = Field(
        default=DocumentStatus.uploading,
        sa_column=Column(String(length=32), nullable=False, index=True),
    )

    # Number of pages extracted from the PDF.
    # Null until extraction completes. Useful for UI and cost estimation.
    page_count: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=True),
    )

    # SHA-256 hash of the raw file bytes.
    # Used for duplicate detection: same bytes -> same checksum.
    # Indexed for fast lookups during dedup checks.
    checksum: str = Field(
        sa_column=Column(String(length=64), nullable=False, index=True)
    )

    # — Extracted Content —
    # Full cleaned text after extraction + normalization.
    # This is what Embeddings will chunk and embed.
    # Text column has no length limit - resumes can be long.
    extracted_text: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )

    error_message: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )

    # — Relationships —
    user: Optional["User"] = Relationship(
        back_populates="documents",
    )

    session: Optional["InterviewSession"] = Relationship(
        back_populates="documents",
    )