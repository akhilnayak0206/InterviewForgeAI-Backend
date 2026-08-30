from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC

from fastapi import HTTPException, UploadFile, status
from sqlmodel import Session, func, select

from app.core.config import settings
from app.documents.enums import DocumentStatus, DocumentType
from app.documents.extractor import (
    extract_text_from_pdf,
    extract_text_from_plain_text,
)
from app.documents.models import Document
from app.documents.storage import (
    compute_checksum,
    generate_storage_filename,
    get_absolute_path,
    save_file,
)
from app.documents.text_processing import normalize_text

logger = logging.getLogger(__name__)


# — Allowed MIME types per document type —
# Resumes: PDF only (structured documents)
# Job Descriptions: PDF or plain text (often copy-pasted)
ALLOWED_MIME_TYPES: dict[DocumentType, set[str]] = {
    DocumentType.resume: {"application/pdf"},
    DocumentType.job_description: {"application/pdf", "text/plain"},
}

# PDF magic bytes - the first 5 bytes of every valid PDF file.
# "%PDF-" in ASCII = bytes 25 50 44 46 2D
PDF_MAGIC_BYTES = b"%PDF-"


async def upload_document(
    *,
    db: Session,
    user_id: uuid.UUID,
    document_type: DocumentType,
    file: UploadFile,
    session_id: uuid.UUID | None = None,
) -> Document:
    """Full document ingestion pipeline.
    Flow:
        1. Validate MIME type
        2. Read file bytes + validate size
        3. Validate content (magic bytes for PDFs)
        4. Compute checksum + check for duplicates
        5. Store file to disk
        6. Create database record (status: uploaded)
        7. Extract text
        8. Normalize text
        9. Update database record (status: processed or failed)

    Returns:
        The persisted Document ORM object with final status.

    Raises:
        HTTPException for validation errors (client-fixable problems).
    """

    # — Step 1: Validate MIME type —
    _validate_mime_type(
        mime_type=file.content_type,
        document_type=document_type,
    )

    # — Step 2: Read file bytes + validate size —
    file_bytes = await file.read()

    _validate_file_size(len(file_bytes))

    # — Step 3: Validate content (magic bytes) —
    # For PDFs, verify the file actually IS a PDF, not a renamed .exe.
    if file.content_type == "application/pdf":
        _validate_pdf_magic_bytes(file_bytes)

    # — Step 4: Compute checksum + duplicate check —
    checksum = compute_checksum(file_bytes)

    _check_duplicate(
        db=db,
        user_id=user_id,
        checksum=checksum,
        session_id=session_id,
    )

    # — Step 5: Store file to disk —
    storage_filename = generate_storage_filename(file.filename or "upload.pdf")

    storage_path = save_file(
        user_id=user_id,
        storage_filename=storage_filename,
        file_bytes=file_bytes,
    )

    # — Step 6: Create database record —
    document = Document(
        user_id=user_id,
        session_id=session_id,
        document_type=document_type,
        original_filename=file.filename or "upload",
        storage_filename=storage_filename,
        mime_type=file.content_type or "application/octet-stream",
        file_size=len(file_bytes),
        storage_path=storage_path,
        status=DocumentStatus.uploaded,
        checksum=checksum,
    )

    db.add(document)
    db.commit()
    db.refresh(document)

    logger.info(
        "Document uploaded | id=%s | user=%s | type=%s | file=%s",
        document.id,
        user_id,
        document_type.value,
        file.filename,
    )

    # — Step 7: Extract text —
    document.status = DocumentStatus.extracting
    db.commit()

    if file.content_type == "application/pdf":
        file_path = get_absolute_path(storage_path)
        result = extract_text_from_pdf(file_path)
    else:
        result = extract_text_from_plain_text(file_bytes)

    # — Step 8: Handle extraction result —
    if not result.success:
        document.status = DocumentStatus.failed
        document.error_message = result.error
        document.page_count = result.page_count

        db.commit()
        db.refresh(document)

        logger.warning(
            "Document extraction failed | id=%s | error=%s",
            document.id,
            result.error,
        )

        return document

    # — Step 9: Normalize text —
    cleaned_text = normalize_text(result.text or "")

    # — Step 10: Update database with results —
    document.status = DocumentStatus.processed
    document.extracted_text = cleaned_text
    document.page_count = result.page_count
    document.error_message = None  # Clear any previous error

    db.commit()
    db.refresh(document)

    logger.info(
        "Document processed | id=%s | pages=%d | text_chars=%d",
        document.id,
        result.page_count,
        len(cleaned_text),
    )

    return document


# — Query Functions —


def get_document_for_user(
    *,
    db: Session,
    document_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Document:
    """Fetch a document by ID and verify ownership.

    Same ownership pattern as session_service.get_session_for_user:
        - Not found -> 404
        - Not yours -> 403
        - Soft-deleted -> 404
    """

    document = db.get(Document, document_id)

    if not document or document.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    if document.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this document.",
        )

    return document


def get_documents_by_user(
    *,
    db: Session,
    user_id: uuid.UUID,
    session_id: uuid.UUID | None = None,
    document_type: DocumentType | None = None,
    offset: int = 0,
    limit: int = 20,
) -> tuple[Sequence[Document], int]:
    """Fetch paginated documents for a user with optional filters.

    Supports filtering by:
        - session_id: only documents for a specific interview session
        - document_type: only resumes or only job descriptions

    Returns (items, total_count). Same pattern as session_service.
    """

    base = select(Document).where(
        Document.user_id == user_id,
        Document.is_deleted == False,
    )

    if session_id is not None:
        base = base.where(Document.session_id == session_id)

    if document_type is not None:
        base = base.where(Document.document_type == document_type)

    total = db.exec(select(func.count()).select_from(base.subquery())).one()

    items = db.exec(base.order_by(Document.created_at.desc()).offset(offset).limit(limit)).all()

    return items, total


def soft_delete_document(
    *,
    db: Session,
    document_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Document:
    """Soft-delete a document owned by the given user.

    Sets is_deleted=True and records the deletion timestamp.
    Does NOT delete the file from storage - that's a future cleanup concern.
    Keeping files allows for undo and audit trails.
    """
    from datetime import datetime

    document = get_document_for_user(
        db=db,
        document_id=document_id,
        user_id=user_id,
    )

    document.is_deleted = True
    document.deleted_at = datetime.now(UTC)

    db.commit()
    db.refresh(document)

    logger.info("Document soft-deleted | id=%s | user=%s", document_id, user_id)

    return document


# — Validation Helpers —
# These are private functions (prefixed with _) because they're only
# called from within this module. They raise HTTPException for
# client-fixable errors.


def _validate_mime_type(
    *,
    mime_type: str | None,
    document_type: DocumentType,
) -> None:
    """Verify the uploaded file's MIME type is allowed for this document type.

    MIME type comes from the HTTP Content-Type header set by the client's
    browser. It's a HINT, not proof - that's why we also check magic bytes.
    """
    if not mime_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File has no content type. Please upload a valid file.",
        )

    allowed = ALLOWED_MIME_TYPES.get(document_type, set())

    if mime_type not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"File type '{mime_type}' is not allowed for {document_type.value}. "
                f"Allowed types: {', '.join(sorted(allowed))}"
            ),
        )


def _validate_file_size(size_bytes: int) -> None:
    """Reject files that exceed the configured maximum size."""
    if size_bytes == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )

    if size_bytes > settings.MAX_UPLOAD_SIZE_BYTES:
        max_mb = settings.MAX_UPLOAD_SIZE_BYTES / (1024 * 1024)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size exceeds maximum allowed size of {max_mb:.0f} MB.",
        )


def _validate_pdf_magic_bytes(file_bytes: bytes) -> None:
    if not file_bytes[:5].startswith(PDF_MAGIC_BYTES):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File does not appear to be a valid PDF.",
        )


def _check_duplicate(
    *,
    db: Session,
    user_id: uuid.UUID,
    checksum: str,
    session_id: uuid.UUID | None,
) -> None:
    """Check if this user already uploaded an identical file.

    Duplicate detection is scoped to user + session:
        - Same file to same session -> rejected (accidental re-upload)
        - Same file to different session -> allowed (different interview)
        - Same file, no session -> check all user's unlinked documents

    Uses SHA-256 checksum: if two files have the same hash,
    they are byte-for-byte identical.
    """

    query = select(Document).where(
        Document.user_id == user_id,
        Document.checksum == checksum,
        Document.is_deleted == False,
    )

    if session_id is not None:
        query = query.where(Document.session_id == session_id)

    existing = db.exec(query).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"This file has already been uploaded (original: '{existing.original_filename}')."
            ),
        )
