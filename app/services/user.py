"""User service — all database operations for the User model.

WHY THIS FILE EXISTS:
    Routes should not contain DB logic directly. By isolating DB operations
    here, we gain:
    - Reusability: the same function works from a route, a CLI, or a test
    - Testability: mock the session, test logic without HTTP
    - Clarity: routes stay thin (HTTP concerns only)

SESSION FLOW IN EACH FUNCTION:
    1. Receive a Session object (injected by FastAPI's Depends)
    2. Build an ORM query or create an ORM model instance
    3. Execute via session.exec() or session.add()
    4. Commit the transaction (for writes)
    5. Refresh the object (to load server-generated values like id, created_at)
    6. Return the ORM model instance (route converts it to a response schema)
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import HTTPException, status
from sqlmodel import Session, select

from app.core.security import hash_password, verify_password
from app.models.user import User
from app.schemas.user import UserCreate


def create_user(*, session: Session, user_in: UserCreate) -> User:
    """Create a new user.

    Flow:
        1. Check if email already exists (prevent duplicate)
        2. Hash the password (placeholder — real hashing comes with auth)
        3. Create a User ORM instance from the schema data
        4. session.add() — stages the INSERT in the session's identity map
        5. session.commit() — sends INSERT to PostgreSQL, commits transaction
        6. session.refresh() — reloads the row so we get server-generated
           values (id, created_at, updated_at)
        7. Return the fully-populated User object
    """

    # Check uniqueness BEFORE attempting insert
    existing = session.exec(
        select(User).where(User.email == user_in.email)
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists.",
        )

    # Hash the plain-text password using bcrypt (via passlib).
    # After this line, the original password is GONE — we only store the hash.
    hashed_password = hash_password(user_in.password)

    db_user = User(
        email=user_in.email,
        hashed_password=hashed_password,
        full_name=user_in.full_name,
    )

    session.add(db_user)      # Stage the INSERT (nothing sent to DB yet)
    session.commit()          # Actually execute INSERT + COMMIT transaction
    session.refresh(db_user)  # Re-SELECT to load server defaults (id, timestamps)

    return db_user


def get_user_by_id(*, session: Session, user_id: uuid.UUID) -> User:
    """Fetch a single user by primary key.

    session.get() is the most efficient way to fetch by PK — it checks
    the identity map first (in-memory cache) before hitting the DB.
    """

    db_user = session.get(User, user_id)

    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    return db_user


def get_user_by_email(*, session: Session, email: str) -> Optional[User]:
    """Fetch a single user by email address.

    Uses select() + where() because email is not the primary key.
    .first() returns None if no row matches (no exception).
    """

    statement = select(User).where(User.email == email)

    return session.exec(statement).first()


def authenticate_user(
    *,
    session: Session,
    email: str,
    password: str
) -> Optional[User]:
    """Verify credentials and return the user if valid, else None.

    This is the LOGIN logic:
        1. Look up user by email
        2. If not found → return None (don't reveal whether email exists)
        3. Verify the plain password against the stored bcrypt hash
        4. If mismatch → return None
        5. If match → return the User

    WHY RETURN None INSTEAD OF RAISING:
        The caller (route) decides the HTTP error. This function is a pure
        service function — it shouldn't know about HTTP status codes for
        auth failures. Keeping it generic means it works from routes,
        CLI tools, background jobs, etc.
    """

    user = get_user_by_email(session=session, email=email)

    if user is None:
        return None

    if not verify_password(password, user.hashed_password):
        return None

    return user