from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncGenerator
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from langgraph.types import Command
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.core.deps import get_current_active_user
from app.core.sse import sse_error, sse_event
from app.db.session import get_db
from app.models.base import MessageRole
from app.models.user import User
from app.schemas.message import MessageCreate
from app.services import message_service, session_service

from app.core.graph import get_interview_graph

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/sessions/{session_id}/interview",
    tags=["interview-workflow"],
)

class InterviewTurnRequest(BaseModel):
    """
    Request body for an interview turn.

    Turn 1 (start): provide resume_text (and optionally max_questions)
    Turn 2+: provide answer
    """

    resume_text: Optional[str] = Field(
        default=None,
        min_length=50,
        description="Resume text — required on the first turn only",
    )

    answer: Optional[str] = Field(
        default=None,
        min_length=1,
        description="Answer to the current question — required on subsequent turns",
    )

    max_questions: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Number of questions to ask (default 5, max 20)",
    )

# ============================================================================
# Streaming Helper
# ============================================================================
async def _stream_interview_turn(
    *,
    graph,
    session_id: str,
    user_id: str,
    body: InterviewTurnRequest,
    db: Session,
) -> AsyncGenerator[str, None]:
    """
    Stream one interview turn as SSE events.

    Determines whether this is a first turn (start) or subsequent turn
    (answer) based on the graph's checkpoint state:
      - No checkpoint exists → first turn → persist resume_text as user message, invoke with initial state
      - Checkpoint exists with interrupt → subsequent turn → persist answer as user message, resume with answer
    """

    config = {"configurable": {"thread_id": session_id}}

    try:
        # Check if there's an existing checkpoint with a pending interrupt
        existing_state = await graph.aget_state(config)
        has_interrupt = bool(existing_state and existing_state.tasks)

        # Check if the interview is already finished
        state_values = existing_state.values if existing_state else {}
        if state_values.get("is_complete"):
            yield sse_error("This interview is already completed. Start a new session.")
            return

        if has_interrupt:
            # — Subsequent turn: resume with the user's answer —
            if not body.answer:
                yield sse_error("Answer is required for this turn.")
                return

            # Persist the user's answer so it appears in the session history.
            message_service.create_message(
                session=db,
                session_id=uuid.UUID(session_id),
                message_in=MessageCreate(role=MessageRole.user, content=body.answer),
            )

            logger.info("Resuming interview | session=%s", session_id)

            async for chunk in graph.astream(
                Command(resume=body.answer),
                config=config,
                stream_mode="updates",
            ):
                node_name, node_output = next(iter(chunk.items()))
                yield sse_event("stage", {
                    "stage": node_name,
                    "data": _sanitize_output(node_output),
                })

        else:
            # — First turn: start a new interview —
            if not body.resume_text:
                yield sse_error("Resume text is required to start an interview.")
                return

            # Persist the user's resume as the first user message.
            message_service.create_message(
                session=db,
                session_id=uuid.UUID(session_id),
                message_in=MessageCreate(
                    role=MessageRole.user,
                    content=body.resume_text,
                ),
            )

            logger.info("Starting interview | session=%s", session_id)

            initial_state = {
                "session_id": session_id,
                "user_id": user_id,
                "resume_text": body.resume_text,
                "max_questions": body.max_questions,
            }

            async for chunk in graph.astream(
                initial_state,
                config=config,
                stream_mode="updates",
            ):
                node_name, node_output = next(iter(chunk.items()))
                yield sse_event("stage", {
                    "stage": node_name,
                    "data": _sanitize_output(node_output),
                })

        # — After stream completes, build the done event —
        final_state = await graph.aget_state(config)
        state_values = final_state.values if final_state else {}
        has_pending = bool(final_state and final_state.tasks)

        done_payload: dict[str, Any] = {
            "is_complete": state_values.get("is_complete", False),
        }

        if has_pending:
            # Graph paused at wait_for_answer → return the question
            done_payload["current_question"] = state_values.get("current_question")
            done_payload["question_number"] = state_values.get("question_number", 0)
            done_payload["max_questions"] = state_values.get("max_questions", 5)

        if state_values.get("current_feedback"):
            done_payload["previous_feedback"] = state_values.get("current_feedback")
            done_payload["previous_score"] = state_values.get("current_score")

        if state_values.get("is_complete"):
            done_payload["final_report"] = state_values.get("final_report")
            scores = state_values.get("scores", [])
            done_payload["average_score"] = (
                round(sum(scores) / len(scores)) if scores else 0
            )

        yield sse_event("done", done_payload)

    except Exception as exc:
        logger.exception("Interview workflow failed | session=%s: %s", session_id, exc)
        yield sse_error(f"Workflow failed: {exc!s}")

def _sanitize_output(node_output: dict) -> dict:
    """
    Remove internal fields from node output before sending to the frontend.
    The frontend doesn't need session_id, user_id, or internal routing fields.
    """
    exclude_keys = {"session_id", "user_id", "is_first_turn", "error"}
    return {k: v for k, v in node_output.items() if k not in exclude_keys}


# ============================================================================
# Route
# ============================================================================


@router.post(
    "",
    summary="Run one interview turn (start or answer)",
)
async def interview_turn(
    session_id: uuid.UUID,
    body: InterviewTurnRequest,
    graph: Any = Depends(get_interview_graph),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Single endpoint for the entire interview lifecycle.

    Turn 1: Send resume_text to start the interview.
    Turn 2+: Send answer to answer the current question.

    Returns an SSE stream with stage events and a final done event.
    The done event contains the current question (if continuing) or
    the final report (if complete).
    """

    # --- Auth: verify session ownership ------------------------------------

    session_service.get_session_for_user(
        session=db,
        session_id=session_id,
        user_id=current_user.id,
    )

    # --- Stream the interview turn -----------------------------------------

    stream = _stream_interview_turn(
        graph=graph,
        session_id=str(session_id),
        user_id=str(current_user.id),
        body=body,
        db=db,
    )

    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
