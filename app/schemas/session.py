"""Pydantic schemas for InterviewSession API input/output."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.models.base import SessionStatus


# --- Request Schemas ---------------------------------------------------------


class SessionCreate(BaseModel):
    """What the client sends to create a new interview session."""

    title: str = Field(
        default="Untitled Session",
        max_length=256
    )


# --- Response Schemas --------------------------------------------------------


class SessionResponse(BaseModel):
    """What the API returns for a single session."""

    id: uuid.UUID
    user_id: uuid.UUID
    title: str
    status: SessionStatus
    summary: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PaginatedSessionResponse(BaseModel):
    """Paginated list of sessions."""

    items: List[SessionResponse]
    total: int
    page: int
    page_size: int