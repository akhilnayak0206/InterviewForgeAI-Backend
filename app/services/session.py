"""InterviewSession service — CRUD operations for interview sessions.

KEY PATTERN: Every write function follows the same rhythm:
    validate → build model → add → commit → refresh → return

KEY PATTERN: Every read function follows:
    build select statement → execute → handle not-found → return
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Sequence, Tuple

from fastapi import HTTPException, status
from sqlmodel import Session, func, select

from app.models.session import InterviewSession
from app.schemas.session import SessionCreate


def create_session(
    *,
    session: Session,
    user_id: uuid.UUID,
    session_in: SessionCreate
) -> InterviewSession:
    """Create a new interview session for a user.

    Note: We accept user_id as a separate parameter rather than embedding it
    in SessionCreate. This is intentional — the user_id will come from auth
    context later, not from the request body. The client should never be
    able to set which user a session belongs to.
    """

    db_session = InterviewSession(
        user_id=user_id,
        title=session_in.title,
    )

    session.add(db_session)
    session.commit()
    session.refresh(db_session)

    return db_session


def get_sessions_by_user(
    *,
    session: Session,
    user_id: uuid.UUID,
    offset: int = 0,
    limit: int = 20
) -> Tuple[Sequence[InterviewSession], int]:
    """Fetch paginated interview sessions for a given user.

    Returns a tuple of (items, total_count). We don't raise 404 for an
    empty list — having zero sessions is a valid state, not an error.

    The query is ordered by created_at descending so the newest session
    appears first — the most common UI expectation.
    """

    base = select(InterviewSession).where(
        InterviewSession.user_id == user_id,
        InterviewSession.is_deleted == False,
    )

    total = session.exec(
        select(func.count()).select_from(base.subquery())
    ).one()

    items = session.exec(
        base.order_by(InterviewSession.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()

    return items, total


def get_session_by_id(
    *,
    session: Session,
    session_id: uuid.UUID
) -> InterviewSession:
    """Fetch a single interview session by its ID."""

    db_session = session.get(InterviewSession, session_id)

    if not db_session or db_session.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Interview session not found.",
        )

    return db_session


def get_session_for_user(
    *,
    session: Session,
    session_id: uuid.UUID,
    user_id: uuid.UUID
) -> InterviewSession:
    """Fetch a session and verify it belongs to the given user.

    This is an OWNERSHIP CHECK — a critical security boundary:
        1. Fetch the session by ID
        2. If it doesn't exist → 404
        3. If it exists but belongs to a different user → 403

    WHY NOT JUST 404 FOR BOTH CASES:
        Some APIs return 404 for both "not found" and "not yours" to prevent
        resource enumeration. That's valid. We use 403 here because:
        - Session IDs are UUIDs (unguessable), so enumeration isn't practical
        - A clear 403 helps the frontend show the right error message
        - It makes debugging easier during development

    This function is used by message routes too — messages are always
    accessed through their parent session, so verifying session ownership
    automatically protects message access.
    """

    db_session = get_session_by_id(
        session=session,
        session_id=session_id
    )

    if db_session.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this session.",
        )

    return db_session


def soft_delete_session(
    *,
    session: Session,
    session_id: uuid.UUID,
    user_id: uuid.UUID
) -> InterviewSession:
    """Soft-delete a session owned by the given user.

    Sets is_deleted=True and records the deletion timestamp.
    The session's messages are also soft-deleted in the same transaction.
    """

    db_session = get_session_for_user(
        session=session,
        session_id=session_id,
        user_id=user_id,
    )

    now = datetime.now(timezone.utc)

    db_session.is_deleted = True
    db_session.deleted_at = now

    # Soft-delete all child messages in the same transaction
    from app.models.message import Message

    messages = session.exec(
        select(Message).where(
            Message.session_id == session_id,
            Message.is_deleted == False,
        )
    ).all()

    for msg in messages:
        msg.is_deleted = True
        msg.deleted_at = now

    session.add(db_session)
    session.commit()
    session.refresh(db_session)

    return db_session