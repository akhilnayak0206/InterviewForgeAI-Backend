"""Message service — CRUD operations for chat messages.

Messages are always scoped to an InterviewSession. Session existence and
ownership are verified by the route layer (via session_service.get_session_for_user)
BEFORE calling these functions. This avoids redundant DB lookups.
"""

from __future__ import annotations

import uuid
from typing import Sequence, Tuple

from sqlmodel import Session, func, select

from app.models.message import Message
from app.schemas.message import MessageCreate


def create_message(
    *,
    session: Session,
    session_id: uuid.UUID,
    message_in: MessageCreate
) -> Message:
    """Add a message to an interview session.

    PRECONDITION: The caller (route) has already verified that the session
    exists, is not soft-deleted, and belongs to the authenticated user via
    session_service.get_session_for_user(). We skip that check here to
    avoid redundant DB hits.

    Flow:
        1. Build the Message ORM object
        2. add() + commit() + refresh()
        3. Return the persisted message
    """

    db_message = Message(
        session_id=session_id,
        role=message_in.role,
        content=message_in.content,
    )

    session.add(db_message)
    session.commit()
    session.refresh(db_message)

    return db_message


def get_messages_by_session(
    *,
    session: Session,
    session_id: uuid.UUID,
    offset: int = 0,
    limit: int = 50
) -> Tuple[Sequence[Message], int]:
    """Fetch paginated messages for a given interview session, ordered chronologically.

    Returns a tuple of (items, total_count). Oldest messages first = natural
    conversation order.
    """

    base = select(Message).where(
        Message.session_id == session_id,
        Message.is_deleted == False,
    )

    total = session.exec(
        select(func.count()).select_from(base.subquery())
    ).one()

    items = session.exec(
        base.order_by(Message.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()

    return items, total