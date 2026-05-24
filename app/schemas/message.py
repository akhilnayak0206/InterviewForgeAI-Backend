"""Pydantic schemas for Message API input/output."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List

from pydantic import BaseModel, Field

from app.models.base import MessageRole


# --- Request Schemas ---------------------------------------------------------


class MessageCreate(BaseModel):
    """What the client sends to add a message to a session."""

    role: MessageRole

    content: str = Field(
        min_length=1,
        max_length=50000,
        description="Message body text"
    )


# --- Response Schemas --------------------------------------------------------


class MessageResponse(BaseModel):
    """What the API returns for a single message."""

    id: uuid.UUID
    session_id: uuid.UUID
    role: MessageRole
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


class PaginatedMessageResponse(BaseModel):
    """Paginated list of messages."""

    items: List[MessageResponse]
    total: int
    page: int
    page_size: int