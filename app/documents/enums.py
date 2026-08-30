from enum import StrEnum


class DocumentType(StrEnum):
    """What kind of document was uploaded."""

    resume = "resume"
    job_description = "job_description"


class DocumentStatus(StrEnum):
    """Processing state of a document."""

    uploading = "uploading"
    uploaded = "uploaded"
    extracting = "extracting"
    processed = "processed"
    embedding = "embedding"
    indexed = "indexed"
    failed = "failed"
