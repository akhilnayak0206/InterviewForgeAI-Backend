import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

# Notice: Mapped is completely gone from imports
from sqlmodel import Field, Relationship

from app.documents.models import Document

from .base import SessionStatus, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from .message import Message
    from .user import User


class InterviewSession(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, table=True):
    __tablename__ = "interview_sessions"

    user_id: uuid.UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("users.id"),
            nullable=False,
            index=True,
        )
    )

    title: str = Field(
        default="Untitled Session",
        sa_column=Column(String(length=256), nullable=False),
    )

    status: SessionStatus = Field(
        default=SessionStatus.active,
        sa_column=Column(String(length=32), nullable=False),
    )

    summary: str | None = Field(
        default=None,
        sa_column=Column(Text),
    )

    user: Optional["User"] = Relationship(
        back_populates="sessions"
    )

    messages: list["Message"] = Relationship(
        back_populates="session",
        sa_relationship_kwargs={"lazy": "selectin"}
    )

    documents: list["Document"] = Relationship(
        back_populates="session",
        sa_relationship_kwargs={"lazy": "selectin"}
    )