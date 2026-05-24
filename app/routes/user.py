"""User routes — PROTECTED endpoints for user profile access.

ALL ROUTES ARE PROTECTED:
    Every route requires a valid JWT via Depends(get_current_active_user).

REMOVED ENDPOINTS:
    - POST /users/ was removed — use POST /auth/signup instead.
      Having two ways to create a user is confusing and the old route
      was unprotected (no auth required).
    - GET /users/by-email/{email} was removed — it allowed unauthenticated
      email enumeration, which undermines login security.

DEPENDS() — HOW DEPENDENCY INJECTION WORKS:
    When FastAPI sees `db: Session = Depends(get_db)`, it:
    1. Calls get_db() which yields a Session
    2. Passes that Session as the `db` argument
    3. After the route returns, resumes get_db() to close the session
    This is a generator-based dependency — the `yield` is the key.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.core.deps import get_current_active_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.user import UserResponse
from app.services import user_service

router = APIRouter(prefix="/users", tags=["Users"])


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    summary="Get a user by ID",
)
def get_user(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Fetch a user by ID — only if it's YOUR own profile.

    This enforces that users can only access their own data.
    For looking up your own profile, prefer GET /auth/me instead.
    """

    if user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only access your own profile.",
        )

    return user_service.get_user_by_id(
        session=db,
        user_id=user_id,
    )