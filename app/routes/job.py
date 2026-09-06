# ruff: noqa: B008
"""Job API — query background job status.

Endpoints:
    GET /jobs            List jobs for the current user (with filters)
    GET /jobs/{job_id}   Get a single job's status and result

Jobs are CREATED by other endpoints (e.g., POST /documents/{id}/embed).
There is no POST /jobs endpoint because jobs are an implementation
detail of specific features, not a user-facing resource that clients
create directly.

Clients use these endpoints to POLL for job completion:
    1. POST /documents/{id}/embed → 202 Accepted {job_id: "..."}
    2. GET /jobs/{job_id} → {status: "running"}
    3. GET /jobs/{job_id} → {status: "completed", result: {...}}
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session

from app.core.deps import get_current_active_user
from app.db.session import get_db
from app.jobs.enums import JobStatus, JobType
from app.models.user import User
from app.schemas.job import JobResponse, PaginatedJobResponse
from app.services import job as job_service

router = APIRouter(
    prefix="/jobs",
    tags=["Jobs"],
)


@router.get(
    "/",
    response_model=PaginatedJobResponse,
    summary="List your background jobs",
)
def list_jobs(
    job_type: JobType | None = Query(default=None, description="Filter by job type"),
    job_status: JobStatus | None = Query(
        default=None, alias="status", description="Filter by status"
    ),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    offset = (page - 1) * page_size

    items, total = job_service.get_jobs_by_user(
        db=db,
        user_id=current_user.id,
        job_type=job_type,
        status=job_status,
        offset=offset,
        limit=page_size,
    )

    return PaginatedJobResponse(
        items=[JobResponse.model_validate(job) for job in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{job_id}",
    response_model=JobResponse,
    summary="Get a job's status and result",
)
def get_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Get the current status of a background job.

    Clients poll this endpoint to check if their job has completed.
    Returns 404 if the job doesn't exist or belongs to another user.
    """
    job = job_service.get_job_for_user(
        db=db,
        job_id=job_id,
        user_id=current_user.id,
    )

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found.",
        )

    return JobResponse.model_validate(job)
