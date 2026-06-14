from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlmodel import Session, select

from app.core.config import settings
from app.core.openai_client import openai_client
from app.models.base import MessageRole
from app.models.message import Message
from app.models.session import InterviewSession
from app.prompts import build_interviewer_system_prompt

logger = logging.getLogger(__name__)


def chat(
    *,
    db: Session,
    interview_session: InterviewSession,
    user_content: str,
) -> dict[str, Any]:
    """
    Main AI chat orchestration flow.

    Flow:
        1. Save user message
        2. Load conversation history
        3. Build system prompt
        4. Format messages for OpenAI
        5. Call OpenAI
        6. Save AI response
        7. Return response + token usage
    """

    # Save the user's message first so it becomes part of history.
    _save_message(
        db=db,
        session_id=interview_session.id,
        role=MessageRole.user,
        content=user_content,
    )

    # Load the complete conversation history.
    history = _load_conversation_history(
        db=db,
        session_id=interview_session.id,
    )

    # Build the system prompt.
    system_prompt = build_interviewer_system_prompt(
        topic=interview_session.title,
    )

    # Convert DB messages into OpenAI format.
    openai_messages = _format_messages_for_openai(
        system_prompt=system_prompt,
        history=history,
    )
    breakpoint()
    # Call OpenAI.
    ai_content, usage = _call_openai(
        messages=openai_messages,
    )

    # Save assistant response.
    ai_message = _save_message(
        db=db,
        session_id=interview_session.id,
        role=MessageRole.assistant,
        content=ai_content,
    )

    logger.info(
        "Chat turn completed | session=%s | prompt_tokens=%d | completion_tokens=%d",
        interview_session.id,
        usage["prompt_tokens"],
        usage["completion_tokens"],
    )

    return {
        "message": ai_message,
        "usage": usage,
    }


def _save_message(
    *,
    db: Session,
    session_id: uuid.UUID,
    role: MessageRole,
    content: str,
) -> Message:
    """
    Persist a message to the database.
    """

    db_message = Message(
        session_id=session_id,
        role=role,
        content=content,
    )

    db.add(db_message)
    db.commit()
    db.refresh(db_message)

    return db_message


def _load_conversation_history(
    *,
    db: Session,
    session_id: uuid.UUID,
) -> list[Message]:
    """
    Load all non-deleted messages for a session ordered oldest → newest.
    """

    statement = (
        select(Message)
        .where(
            Message.session_id == session_id,
            not Message.is_deleted,
        )
        .order_by(Message.created_at.asc())
    )

    return list(db.exec(statement).all())


def _format_messages_for_openai(
    *,
    system_prompt: str,
    history: list[Message],
) -> list[dict[str, str]]:
    """
    Convert database messages into OpenAI chat format.
    """

    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": system_prompt,
        }
    ]

    for msg in history:
        if msg.role == MessageRole.system:
            continue

        messages.append(
            {
                "role": msg.role.value,
                "content": msg.content,
            }
        )

    return messages


def _call_openai(
    *,
    messages: list[dict[str, str]],
) -> tuple[str, dict[str, int]]:
    """
    Execute a chat completion request.
    """

    response = openai_client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=messages,
        max_tokens=settings.OPENAI_MAX_TOKENS,
        temperature=settings.OPENAI_TEMPERATURE,
    )

    content = response.choices[0].message.content or ""

    usage = {
        "prompt_tokens": response.usage.prompt_tokens,
        "completion_tokens": response.usage.completion_tokens,
        "total_tokens": response.usage.total_tokens,
    }

    return content, usage
