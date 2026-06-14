from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from openai import APIConnectionError, APIStatusError, RateLimitError
from sqlmodel import Session

from app.core.deps import get_current_active_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.chat import ChatRequest, ChatResponse, TokenUsage
from app.services import ai_service, session_service

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/sessions/{session_id}/chat",
    tags=["AI Chat"],
)


@router.post(
    "/",
    response_model=ChatResponse,
    summary="Send a message and get an AI response",
    responses={
        502: {"description": "LLM provider error"},
        429: {"description": "LLM rate limit exceeded"},
    },
)
def chat(
    session_id: uuid.UUID,
    chat_in: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Send a message to the AI interviewer and get a response.

    The user's message is saved to the database BEFORE the AI is called.
    If the AI call fails, the user's message is still preserved and they
    can retry without re-typing.

    The AI receives the FULL conversation history for this session,
    maintaining context across multiple turns.
    """

    # --- Authorization: verify session ownership ------------------------

    interview_session = session_service.get_session_for_user(
        session=db,
        session_id=session_id,
        user_id=current_user.id,
    )

    # --- Delegate to AI service ----------------------------------------

    try:
        result = ai_service.chat(
            db=db,
            interview_session=interview_session,
            user_content=chat_in.content,
        )

    except RateLimitError:
        logger.warning(
            "OpenAI rate limit hit | user=%s",
            current_user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="AI service is temporarily overloaded. Please try again in a few sec..."
        )

    except APIConnectionError:
        logger.error("Failed to connect to OpenAI API")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to reach the AI service. Please try again later.",
        )

    except APIStatusError as exc:
        logger.error(
            "OpenAI API error | status=%d | message=%s",
            exc.status_code,
            exc.message,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI service returned an error. Please try again later.",
        )

    # --- Build response ------------------------------------------------

    return ChatResponse(
        message=result["message"],
        usage=TokenUsage(**result["usage"]),
    )