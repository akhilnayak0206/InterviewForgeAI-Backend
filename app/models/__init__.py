"""Import every table model here for SQLModel metadata registration."""

from app.documents.chunk_models import DocumentChunk
from app.documents.models import Document

from .base import CreatedAtMixin, MessageRole, SessionStatus, TimestampMixin, UUIDPrimaryKeyMixin
from .message import Message
from .session import InterviewSession
from .user import User

__all__ = [
    "User",
    "InterviewSession",
    "Message",
    "SessionStatus",
    "MessageRole",
    "UUIDPrimaryKeyMixin",
    "CreatedAtMixin",
    "TimestampMixin",
    "Document",
    "DocumentChunk",
]
