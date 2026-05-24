from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from typing import Optional

from sqlalchemy import Boolean, Column, DateTime, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class UUIDPrimaryKeyMixin(SQLModel):
    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        nullable=False,
        sa_type=PG_UUID(as_uuid=True),
    )


class CreatedAtMixin(SQLModel):
    created_at: datetime = Field(
        default_factory=utc_now,
        nullable=False,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"server_default": func.now()},
    )


class TimestampMixin(CreatedAtMixin):
    updated_at: datetime = Field(
        default_factory=utc_now,
        nullable=False,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"server_default": func.now(), "onupdate": func.now()},
    )

class SoftDeleteMixin(SQLModel):
    is_deleted: bool = Field(default=False, index=True)
    deleted_at: Optional[datetime] = Field(default=None)

class SessionStatus(str, Enum):
    draft = "draft"
    active = "active"
    completed = "completed"
    archived = "archived"


class MessageRole(str, Enum):
    user = "user"
    assistant = "assistant"
    system = "system"
