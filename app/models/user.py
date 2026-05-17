from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

from sqlmodel import Field, Relationship
from sqlalchemy import Boolean, Column, String

if TYPE_CHECKING:
    from .session import InterviewSession

from .base import TimestampMixin, UUIDPrimaryKeyMixin


class User(UUIDPrimaryKeyMixin, TimestampMixin, table=True):
    __tablename__ = "users"

    email: str = Field(
        sa_column=Column(String(length=320), unique=True, nullable=False, index=True)
    )

    hashed_password: str = Field(sa_column=Column(String, nullable=False))
    full_name: Optional[str] = Field(default=None, sa_column=Column(String(length=256)))
    is_active: bool = Field(default=True, sa_column=Column(Boolean, nullable=False, index=True))

    sessions: List["InterviewSession"] = Relationship(back_populates="user")
