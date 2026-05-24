"""InterviewSession routes — PROTECTED endpoints for session CRUD.

ALL ROUTES ARE PROTECTED:
    Every route requires a valid JWT via Depends(get_current_active_user).
    The user_id is extracted from the token — the client NEVER supplies it.

OWNERSHIP MODEL:
    - create_session: user_id comes from current_user.id
    - get_user_sessions: lists only the authenticated user's sessions
    - get_session: fetches by ID + verifies ownership (403 if not yours)
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlmodel import Session

from app.core.deps import get_current_active_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.session import (
    PaginatedSessionResponse,
    SessionCreate,
    SessionResponse,
)
from app.services import session_service

router = APIRouter(
    prefix="/sessions",
    tags=["Interview Sessions"],
)


@router.post(
    "/",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new interview session",
)
def create_session(
    session_in: SessionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Create a session owned by the authenticated user.

    Before auth: user_id was a query parameter (the client chose it).
    After auth: user_id comes from the JWT token (the server decides it).

    The service layer didn't change at all — only the route did.
    """

    return session_service.create_session(
        session=db,
        user_id=current_user.id,
        session_in=session_in,
    )


@router.get(
    "/",
    response_model=PaginatedSessionResponse,
    summary="Get paginated sessions for the authenticated user",
)
def get_user_sessions(
    page: int = Query(
        1,
        ge=1,
        description="Page number (1-indexed)",
    ),
    page_size: int = Query(
        20,
        ge=1,
        le=100,
        description="Items per page",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """List sessions for the currently logged-in user.

    Before auth:
        URL was /sessions/user/{user_id}
        Anyone could list anyone's sessions by guessing UUIDs.

    After auth:
        URL is /sessions/
        Users can ONLY see their own.
        The user_id is implicit from the token.
    """

    offset = (page - 1) * page_size

    items, total = session_service.get_sessions_by_user(
        session=db,
        user_id=current_user.id,
        offset=offset,
        limit=page_size,
    )

    return PaginatedSessionResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{session_id}",
    response_model=SessionResponse,
    summary="Get a single session by ID",
)
def get_session(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Fetch a session by ID — only if it belongs to the authenticated user.

    Uses get_session_for_user which does the ownership check:
    if the session exists but belongs to someone else → 403 Forbidden.
    """

    return session_service.get_session_for_user(
        session=db,
        session_id=session_id,
        user_id=current_user.id,
    )


@router.delete(
    "/{session_id}",
    response_model=SessionResponse,
    summary="Soft-delete a session",
)
def delete_session(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Soft-delete a session and all its messages.

    The session is not permanently removed:
    - is_deleted is set to True
    - deleted_at timestamp is recorded
    - all child messages are soft-deleted in the same transaction
    """

    return session_service.soft_delete_session(
        session=db,
        session_id=session_id,
        user_id=current_user.id,
    )