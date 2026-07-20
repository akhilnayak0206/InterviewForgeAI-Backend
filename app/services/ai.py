from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, AsyncGenerator

from sqlmodel import Session, select

from app.core.config import settings
from app.core.openai_client import openai_client
from app.models.base import MessageRole
from app.models.message import Message
from app.models.session import InterviewSession
from app.prompts import build_interviewer_system_prompt
from interviewforgeai_backend.app.core.providers import get_provider
from interviewforgeai_backend.app.core.sse import sse_event

logger = logging.getLogger(__name__)


def chat(
    *,
    session: Session,
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
        session=session,
        session_id=interview_session.id,
        role=MessageRole.user,
        content=user_content,
    )

    # Load the complete conversation history.
    history = _load_conversation_history(
        session=session,
        session_id=interview_session.id,
    )

    # Build the system prompt.
    system_prompt = build_interviewer_system_prompt(
        topic=interview_session.title,
    )

    # Convert DB messages into LLM format.
    messages = _format_messages_for_llm(
        system_prompt=system_prompt,
        history=history,
    )

    # Call LLM.
    ai_content, usage = _call_openai(
        messages=messages,
    )

    # Save assistant response.
    ai_message = _save_message(
        session=session,
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
    session: Session,
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

    session.add(db_message)
    session.commit()
    session.refresh(db_message)

    return db_message


def _load_conversation_history(
    *,
    session: Session,
    session_id: uuid.UUID,
) -> list[Message]:
    """
    Load all non-deleted messages for a session ordered oldest → newest.
    """

    statement = (
        select(Message)
        .where(
            Message.session_id == session_id,
            Message.is_deleted.is_(False),
        )
        .order_by(Message.created_at.asc())
    )

    return list(session.exec(statement).all())


def _format_messages_for_llm(
    *,
    system_prompt: str,
    history: list[Message],
) -> list[dict[str, str]]:
    """
    Convert database messages into LLM chat format.
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
                "role": msg.role,
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

# PLEASE NOTE ONLY THIS SERVICE SUPPORTS MULTIPLE PROVIDERS
async def stream_chat(
    *,
    session: Session,
    interview_session: InterviewSession,
    user_content: str,
) -> AsyncGenerator[str, None]:
    """
    Stream AI response tokens as SSE events.

    Flow:
        1. Save user message (sync — happens before streaming starts)
        2. Load conversation history
        3. Build system prompt + format messages
        4. Open streaming connection to OpenAI
        5. Yield each token as an SSE event
        6. After stream completes, save full response to DB
        7. Yield a "done" event with the persisted message ID

    Cancellation:
        If the client disconnects mid-stream, asyncio.CancelledError
        is raised. The finally block saves whatever was collected so
        the partial response isn't lost.
    """

    # — Pre-stream: save user message + prepare context ——————————

    _save_message(
        session=session,
        session_id=interview_session.id,
        role=MessageRole.user,
        content=user_content,
    )

    history = _load_conversation_history(
        session=session,
        session_id=interview_session.id,
    )

    system_prompt = build_interviewer_system_prompt(
        topic=interview_session.title,
    )

    messages = _format_messages_for_llm(
        system_prompt=system_prompt,
        history=history,
    )

    # — Stream tokens from the configured provider ——————————————

    provider = get_provider()
    collected_tokens: list[str] = []
    stream_completed = False

    try:
        async for token in provider.stream(messages):
            collected_tokens.append(token)
            yield sse_event("token", {"content": token})

        stream_completed = True

    except asyncio.CancelledError:
        logger.info(
            "Client disconnected mid-stream | session=%s | "
            "tokens_collected=%d",
            interview_session.id,
            len(collected_tokens),
        )
        raise

    finally:
        # — Post-stream: persist the AI response ————————————
        if collected_tokens:
            full_content = "".join(collected_tokens)
            ai_message = _save_message(
                session=session,
                session_id=interview_session.id,
                role=MessageRole.assistant,
                content=full_content,
            )

            logger.info(
                "Stream %s | session=%s | tokens=%d | chars=%d",
                "completed" if stream_completed else "partial (client disconnected)",
                interview_session.id,
                len(collected_tokens),
                len(full_content),
            )

    # — Signal completion to the client ——————————————————

    yield sse_event("done", {"message_id": str(ai_message.id)})