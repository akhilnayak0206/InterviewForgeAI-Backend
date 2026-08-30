from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from pydantic import BaseModel, Field

from app.documents.enums import DocumentStatus, DocumentType


class DocumentResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    session_id: uuid.UUID | None
    document_type: DocumentType
    original_filename: str
    mime_type: str
    file_size: int
    status: DocumentStatus
    page_count: int | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentDetailResponse(DocumentResponse):
    """Extended response that includes extracted text.

    Use this for single-document detail views where the frontend
    needs to display the extracted content.
    Inherits all fields from DocumentResponse + adds extracted_text.
    """

    extracted_text: str | None


class PaginatedDocumentResponse(BaseModel):
    """Paginated list of documents."""

    items: Sequence[DocumentResponse]
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)


class EmbeddingResponse(BaseModel):
    """Response from the embedding pipeline.

    Returned by POST /documents/{id}/embed.
    Tells the client whether embedding succeeded and how many
    chunks were created.
    """

    success: bool
    document_id: uuid.UUID
    chunks_created: int
    total_tokens: int
    error: str | None = None
