from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.message import MessageResponse


class ChatRequest(BaseModel):
    """What the client sends to the chat endpoint.

    Notice: NO role field. The chat endpoint always treats
    the incoming message as a "user" message. This is a deliberate
    design choice - the client should never be able to inject
    "assistant" or "system" messages through the chat flow.
    """

    content: str = Field(
        min_length=1,
        max_length=50000,
        description="The user's message to the AI interviewer",
    )


class TokenUsage(BaseModel):
    """Token consumption for a single AI request.

    WHY TRACK THIS:
    - Cost monitoring: each token costs money
    - Context budget: helps you detect when conversations are getting
      too long and approaching the model's context window limit
    - Debugging: if responses are getting truncated, check if
      completion_tokens == max_tokens (that means the model hit the cap)
    """

    prompt_tokens: int = Field(
        description="Tokens used by the input (history + system prompt)"
    )

    completion_tokens: int = Field(
        description="Tokens used by the AI's response"
    )

    total_tokens: int = Field(
        description="Sum of prompt + completion tokens"
    )


class ChatResponse(BaseModel):
    """What the chat endpoint returns.

    Includes the persisted AI message (with its DB id, timestamps, etc.)
    plus token usage metadata. The user's message was already saved
    before the AI was called, so the client can fetch it via the
    regular message list endpoint if needed.
    """

    message: MessageResponse = Field(
        description="The AI's response, persisted to DB"
    )

    usage: TokenUsage = Field(
        description="Token consumption for this request"
    )