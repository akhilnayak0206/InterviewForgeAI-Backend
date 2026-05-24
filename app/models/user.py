from typing import TYPE_CHECKING, List, Optional

# Notice: Mapped is completely gone from imports
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

    # FIX: Clean standard list type hint + production optimization argument
    sessions: List["InterviewSession"] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={"lazy": "selectin"}
    )