"""Routes module for API endpoints"""

from .auth import router as auth_router
from .user import router as user_router
from .session import router as session_router
from .message import router as message_router
from .chat import router as chat_router
from .interview_workflow import router as interview_workflow_router

__all__ = [
    "auth_router",
    "user_router",
    "session_router",
    "message_router",
    "chat_router",
    "interview_workflow_router",
]