from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship
from sqlalchemy import Column, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from .base import CreatedAtMixin, MessageRole, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from .session import InterviewSession


class Message(UUIDPrimaryKeyMixin, CreatedAtMixin, table=True):
    __tablename__ = "messages"

    session_id: uuid.UUID = Field(
        sa_column=Column(PG_UUID(as_uuid=True), ForeignKey("interview_sessions.id"), nullable=False, index=True),
    )

    role: MessageRole = Field(sa_column=Column(String(length=32), nullable=False))
    content: str = Field(sa_column=Column(Text, nullable=False))

    session: Optional["InterviewSession"] = Relationship(back_populates="messages")
