# ruff: noqa: B008
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from sqlmodel import Session

from app.core.deps import get_current_active_user
from app.db.session import get_db
from app.documents import embedding_pipeline
from app.documents import service as document_service
from app.documents.enums import DocumentType
from app.documents.schemas import (
    DocumentDetailResponse,
    DocumentResponse,
    EmbeddingResponse,
    PaginatedDocumentResponse,
)
from app.models.user import User

router = APIRouter(
    prefix="/documents",
    tags=["Documents"],
)


@router.post(
    "/upload",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload and process a document",
)
async def upload_document(
    document_type: DocumentType = Query(
        ...,
        description="Type of document: 'resume' or 'job_description'",
    ),
    session_id: uuid.UUID | None = Query(
        default=None,
        description="Optional interview session to link this document to",
    ),
    file: UploadFile = File(
        ...,
        description="PDF file (or .txt for job descriptions)",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Upload a document, extract text, and prepare it for embeddings.

    The full ingestion pipeline runs synchronously:
        1. Validate file type and size
        2. Check for duplicates
        3. Store file to disk
        4. Extract text from PDF
        5. Normalize extracted text
        6. Persist everything to the database

    The response includes the processing status:
        - "processed" -> text was extracted successfully
        - "failed" -> extraction failed (check error_message)

    In a future section, extraction could be offloaded to a background
    worker. For now, synchronous processing keeps the architecture simple.
    """
    return await document_service.upload_document(
        db=db,
        user_id=current_user.id,
        document_type=document_type,
        file=file,
        session_id=session_id,
    )


@router.get(
    "/",
    response_model=PaginatedDocumentResponse,
    summary="List your documents",
)
def list_documents(
    session_id: uuid.UUID | None = Query(
        default=None,
        description="Filter by interview session",
    ),
    document_type: DocumentType | None = Query(
        default=None,
        description="Filter by document type",
    ),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    offset = (page - 1) * page_size

    items, total = document_service.get_documents_by_user(
        db=db,
        user_id=current_user.id,
        session_id=session_id,
        document_type=document_type,
        offset=offset,
        limit=page_size,
    )

    return PaginatedDocumentResponse(
        items=[DocumentResponse.model_validate(document) for document in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{document_id}",
    response_model=DocumentDetailResponse,
    summary="Get a document with extracted text",
)
def get_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    return document_service.get_document_for_user(
        db=db,
        document_id=document_id,
        user_id=current_user.id,
    )


@router.delete(
    "/{document_id}",
    response_model=DocumentResponse,
    summary="Soft-delete a document",
)
def delete_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    return document_service.soft_delete_document(
        db=db,
        document_id=document_id,
        user_id=current_user.id,
    )


@router.post(
    "/{document_id}/embed",
    response_model=EmbeddingResponse,
    summary="Embed a processed document for semantic search",
)
def embed_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Run the embedding pipeline on a processed document.

    Chunks the document text, generates vector embeddings via OpenAI,
    and stores them in the database for future semantic search.

    Preconditions:
        - Document must be in 'processed' or 'indexed' status.
        - Calling on an 'indexed' document re-embeds it (idempotent).

    Returns embedding metrics: chunks created, tokens consumed.
    """
    document = document_service.get_document_for_user(
        db=db,
        document_id=document_id,
        user_id=current_user.id,
    )

    result = embedding_pipeline.embed_document(
        db=db,
        document=document,
    )

    return EmbeddingResponse(
        success=result.success,
        document_id=result.document_id,
        chunks_created=result.chunks_created,
        total_tokens=result.total_tokens,
        error=result.error,
    )
