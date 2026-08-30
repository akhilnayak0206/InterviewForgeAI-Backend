from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Column, String
from sqlmodel import Field, Relationship

if TYPE_CHECKING:
    from app.documents.models import Document

    from .session import InterviewSession

from .base import TimestampMixin, UUIDPrimaryKeyMixin


class User(UUIDPrimaryKeyMixin, TimestampMixin, table=True):
    __tablename__ = "users"

    email: str = Field(
        sa_column=Column(String(length=320), unique=True, nullable=False, index=True)
    )

    hashed_password: str = Field(sa_column=Column(String, nullable=False))
    full_name: str | None = Field(default=None, sa_column=Column(String(length=256)))
    is_active: bool = Field(default=True, sa_column=Column(Boolean, nullable=False, index=True))

    # FIX: Clean standard list type hint + production optimization argument
    sessions: list["InterviewSession"] = Relationship(
        back_populates="user", sa_relationship_kwargs={"lazy": "selectin"}
    )

    documents: list["Document"] = Relationship(
        back_populates="user", sa_relationship_kwargs={"lazy": "selectin"}
    )
