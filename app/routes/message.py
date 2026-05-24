"""Message routes — PROTECTED endpoints for message CRUD.

Messages are always nested under a session.
The URL structure reflects this parent-child relationship:

    /sessions/{session_id}/messages

SECURITY MODEL:

Messages don't have their own user_id.
They belong to a session, and the session belongs to a user.

So we protect messages by verifying session ownership first.

If you don't own the session:
    → you can't create/read its messages.

This is called TRANSITIVE AUTHORIZATION:
the parent's ownership cascades to the children.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlmodel import Session

from app.core.deps import get_current_active_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.message import (
    MessageCreate,
    MessageResponse,
    PaginatedMessageResponse,
)
from app.services import message_service, session_service

router = APIRouter(
    prefix="/sessions/{session_id}/messages",
    tags=["Messages"],
)


@router.post(
    "/",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a message to a session",
)
def create_message(
    session_id: uuid.UUID,
    message_in: MessageCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Add a message to a session owned by the authenticated user.

    Ownership check happens FIRST via get_session_for_user:

        - Session doesn't exist        → 404
        - Session belongs to someone   → 403
        - Session is yours             → proceed to create message
    """

    session_service.get_session_for_user(
        session=db,
        session_id=session_id,
        user_id=current_user.id,
    )

    return message_service.create_message(
        session=db,
        session_id=session_id,
        message_in=message_in,
    )


@router.get(
    "/",
    response_model=PaginatedMessageResponse,
    summary="Get paginated messages for a session",
)
def get_session_messages(
    session_id: uuid.UUID,
    page: int = Query(
        1,
        ge=1,
        description="Page number (1-indexed)",
    ),
    page_size: int = Query(
        50,
        ge=1,
        le=100,
        description="Items per page",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """List messages for a session — only if the session belongs to you."""

    # Verify ownership BEFORE exposing messages
    session_service.get_session_for_user(
        session=db,
        session_id=session_id,
        user_id=current_user.id,
    )

    offset = (page - 1) * page_size

    items, total = message_service.get_messages_by_session(
        session=db,
        session_id=session_id,
        offset=offset,
        limit=page_size,
    )

    return PaginatedMessageResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )