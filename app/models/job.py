"""Job model — durable record of every background task.

This table is the SOURCE OF TRUTH for job state. The queue (Redis)
is transient coordination infrastructure — it tells workers "do this."
PostgreSQL tells the application "this is what happened."

Design decisions:
    - payload and result are JSON columns. Different job types need
      different inputs/outputs. JSON avoids a separate table per job type.
    - max_attempts defaults to 3. This can be overridden per-job when
      the producer creates it (some jobs are more or less retryable).
    - error stores only the LAST error. Previous errors are in logs.
      Storing every error in the DB would bloat the table for little value.
    - started_at is the timestamp of the CURRENT attempt, not the first.
      Useful for detecting stuck jobs: if started_at was 30 minutes ago
      and status is still 'running', the worker probably died.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlmodel import Field

from app.jobs.enums import JobStatus, JobType
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class Job(UUIDPrimaryKeyMixin, TimestampMixin, table=True):
    __tablename__ = "jobs"

    # — Ownership —
    # Every job belongs to a user. Multi-tenant isolation: users can
    # only query/cancel their own jobs.
    user_id: uuid.UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("users.id"),
            nullable=False,
            index=True,
        )
    )

    # — What and Where —
    # job_type determines which handler function the worker calls.
    # Indexed because we query "all failed embedding jobs" for monitoring.
    job_type: JobType = Field(sa_column=Column(String(length=64), nullable=False, index=True))

    # — Lifecycle —
    status: JobStatus = Field(
        default=JobStatus.pending,
        sa_column=Column(String(length=32), nullable=False, index=True),
    )

    # — Input / Output —
    # payload: the job's input data. For embed_document: {"document_id": "..."}
    # result: the job's output data. For embed_document: {"chunks_created": 12}
    # Both are JSON because different job types have different shapes.
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    result: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))

    # — Error Tracking —
    error: str | None = Field(default=None, sa_column=Column(Text, nullable=True))

    # — Progress Tracking —
    # progress: 0-100 integer percentage. Updated by the task function
    #   at meaningful milestones. Don't update every iteration — a few
    #   updates per job is enough for a responsive UI.
    # progress_message: human-readable stage label (e.g., "Generating embeddings")
    progress: int = Field(default=0, sa_column=Column(Integer, nullable=False))
    progress_message: str | None = Field(
        default=None,
        sa_column=Column(String(length=256), nullable=True),
    )

    # — Retry Tracking —
    # attempts: how many times a worker has tried this job. Starts at 0.
    # max_attempts: the retry budget. When attempts >= max_attempts, the job
    #   transitions to 'dead' instead of being retried.
    attempts: int = Field(default=0, sa_column=Column(Integer, nullable=False))
    max_attempts: int = Field(default=3, sa_column=Column(Integer, nullable=False))

    # — Timestamps —
    # started_at: when the current attempt began. Reset on each retry.
    # completed_at: when the job finished (success or permanent failure).
    started_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )

    completed_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
