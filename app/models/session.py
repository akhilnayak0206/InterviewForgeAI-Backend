from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, List, Optional

from sqlmodel import Field, Relationship
from sqlalchemy import Column, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from .base import SessionStatus, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from .user import User
    from .message import Message


class InterviewSession(UUIDPrimaryKeyMixin, TimestampMixin, table=True):
    __tablename__ = "interview_sessions"

    user_id: uuid.UUID = Field(
        sa_column=Column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True),
    )

    title: str = Field(default="Untitled Session", sa_column=Column(String(length=256), nullable=False))
    status: SessionStatus = Field(default=SessionStatus.active, sa_column=Column(String(length=32), nullable=False))
    summary: Optional[str] = Field(default=None, sa_column=Column(Text))

    user: Optional["User"] = Relationship(back_populates="sessions")
    messages: List["Message"] = Relationship(back_populates="session")
