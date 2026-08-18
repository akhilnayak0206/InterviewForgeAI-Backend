from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


@dataclass
class ExtractionResult:
    success: bool
    text: str | None
    page_count: int
    error: str | None = None


def extract_text_from_pdf(file_path: Path) -> ExtractionResult:
    """Extract text from a PDF file.

    Opens the PDF, iterates over every page, extracts text from each,
    and concatenates them with page separators.

    Args:
        file_path: Absolute path to the PDF file on disk.

    Returns:
        ExtractionResult with extracted text and metadata.

    NEVER RAISES - all exceptions are caught and returned as errors.
    This is intentional: the caller (service.py) handles failures
    by updating the document status to "failed" with the error message.
    """

    if not file_path.exists():
        return ExtractionResult(
            success=False,
            text=None,
            page_count=0,
            error=f"File not found: {file_path}",
        )

    try:
        doc = fitz.open(str(file_path))
    except Exception as exc:
        logger.error("Failed to open PDF | path=%s | error=%s", file_path, exc)
        return ExtractionResult(
            success=False,
            text=None,
            page_count=0,
            error=f"Failed to open PDF: {exc}",
        )

    try:
        # Check for encryption/password protection BEFORE extracting.
        # fitz.open() succeeds on encrypted PDFs, but text extraction
        # returns garbage or empty strings.
        if doc.is_encrypted:
            doc.close()
            return ExtractionResult(
                success=False,
                text=None,
                page_count=doc.page_count,
                error="PDF is password-protected. Please upload an unprotected PDF.",
            )

        page_count = doc.page_count

        if page_count == 0:
            doc.close()
            return ExtractionResult(
                success=False,
                text=None,
                page_count=0,
                error="PDF has zero pages.",
            )

        # Extract text from each page.
        # We use "text" mode which gives plain text (no layout preservation).
        # For resumes and JDs, plain text is what we want - layout doesn't
        # matter for LLM consumption.
        page_texts: list[str] = []

        for page_num in range(page_count):
            page = doc[page_num]
            page_text = page.get_text("text")
            page_texts.append(page_text)

        doc.close()

        # Join pages with double newline separator.
        # This preserves page boundaries without adding artificial markers.
        full_text = "\n\n".join(page_texts)

        # Check if we actually got any text.
        # Scanned PDFs will produce pages of empty/whitespace-only strings.
        stripped = full_text.strip()
        if not stripped:
            return ExtractionResult(
                success=False,
                text=None,
                page_count=page_count,
                error=(
                    "No text could be extracted from this PDF. "
                    "It may be a scanned document (image-only). "
                    "Please upload a PDF with selectable text."
                ),
            )

        logger.info(
            "PDF extracted | path=%s | pages=%d | chars=%d",
            file_path,
            page_count,
            len(full_text),
        )

        return ExtractionResult(
            success=True,
            text=full_text,
            page_count=page_count,
        )

    except Exception as exc:
        doc.close()
        logger.error(
            "PDF extraction failed | path=%s | error=%s",
            file_path,
            exc,
        )
        return ExtractionResult(
            success=False,
            text=None,
            page_count=0,
            error=f"Text extraction failed: {exc}",
        )


def extract_text_from_plain_text(file_bytes: bytes) -> ExtractionResult:
    """Extract text from a plain text file (for job descriptions).

    Much simpler than PDF - just decode the bytes. But we still need
    to handle encoding errors and empty files.

    WHY SUPPORT PLAIN TEXT:
        Job descriptions are often copy-pasted into .txt files.
        Supporting text upload alongside PDF makes the UX smoother.
    """

    try:
        text = file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = file_bytes.decode("latin-1")
        except Exception as exc:
            return ExtractionResult(
                success=False,
                text=None,
                page_count=0,
                error=f"Could not decode text file: {exc}",
            )

    stripped = text.strip()
    if not stripped:
        return ExtractionResult(
            success=False,
            text=None,
            page_count=0,
            error="Text file is empty.",
        )

    return ExtractionResult(
        success=True,
        text=text,
        page_count=1,  # Plain text files are "1 page"
    )