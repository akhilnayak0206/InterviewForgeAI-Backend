"""Pydantic schemas for User API input/output.

These schemas define the API CONTRACT — what data comes in and what goes out.
They are intentionally separate from the ORM model because:
- UserCreate accepts a raw password; the model stores a HASH
- UserResponse never exposes hashed_password
- Validation rules (email format, min length) belong here, not on the DB model
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


# --- Request Schemas ---------------------------------------------------------


class UserCreate(BaseModel):
    """What the client sends to POST /users."""

    email: EmailStr

    password: str = Field(
        min_length=8,
        description="Plain-text password (will be hashed)"
    )

    full_name: Optional[str] = Field(
        default=None,
        max_length=256
    )


# --- Response Schemas --------------------------------------------------------


class UserResponse(BaseModel):
    """What the API returns for a single user. Never includes password."""

    id: uuid.UUID
    email: str
    full_name: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}