"""Import every table model here for SQLModel metadata registration."""

from .base import CreatedAtMixin, MessageRole, SessionStatus, TimestampMixin, UUIDPrimaryKeyMixin
from .job import Job
from .message import Message
from .session import InterviewSession
from .user import User

__all__ = [
    "User",
    "InterviewSession",
    "Message",
    "Job",
    "SessionStatus",
    "MessageRole",
    "UUIDPrimaryKeyMixin",
    "CreatedAtMixin",
    "TimestampMixin",
]
