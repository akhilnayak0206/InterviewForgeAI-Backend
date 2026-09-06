"""Pydantic schemas for the Job API.

Follows the same pattern as your document and session schemas:
    - Lean response models with from_attributes
    - Paginated list response
    - No "create" schema exposed to clients (jobs are created
      by the system, not by direct user POST to /jobs)
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.jobs.enums import JobStatus, JobType


class JobResponse(BaseModel):
    """What the API returns for a single job.

    This is what the client polls to check job progress.
    """

    id: uuid.UUID
    user_id: uuid.UUID
    job_type: JobType
    status: JobStatus
    payload: dict
    result: dict | None
    error: str | None
    progress: int
    progress_message: str | None
    attempts: int
    max_attempts: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class PaginatedJobResponse(BaseModel):
    """Paginated list of jobs."""

    items: list[JobResponse]
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
