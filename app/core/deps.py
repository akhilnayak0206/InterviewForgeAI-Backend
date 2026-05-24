"""
FASTAPI dependencies for authentication.

DEPENDENCY INJECTION
This file defines a chain of dependencies that FastAPI resolves
automatically before your route handler runs:

1. oauth2_scheme: Extracts the bearer token from the Authorization header
2. get_current_user: Decodes the JWT + fetches the user from DB
3. get_current_active_user: Verifies the user's account is active

In a route, you just write:

    @router.get("/me")
    def read_current_user(user: User = Depends(get_current_active_user)):
        ...

and FastAPI runs the ENTIRE chain for you.

WHY OAuth2PasswordBearer WORKS:
It's a FastAPI class that does two things:
1. Tells Swagger UI to show a login button (tokenUrl)
2. Extracts the token from "Authorization: Bearer <token>"
It does NOT validate the token — that's your job in get_current_user.

WHY SEPARATE:
Separating get_current_user AND get_current_active_user
keeps concerns clean. get_current_user handles token validation,
DB lookup, etc.
This makes it easy to add more layers later (e.g. email verification).
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from sqlmodel import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.user import User


# --- OAuth2 Scheme -----------------------------------------------------------

"""
tokenUrl is the path where the client sends credentials to get a token.
This is relative to the FastAPI app's root for Swagger UI.
"Authorize" dialog. It must match the actual login endpoint path.
"""

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/login"
)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    Decode JWT token and return the corresponding user.

    This dependency is the core of request authentication. Here's the
    complete flow when FastAPI resolves this dependency:

    1. oauth2_scheme extracts the token from "Authorization: Bearer <token>"
    2. jwt.decode() verifies the signature and checks expiration.
    3. We extract the "sub" claim (user ID) from the payload.
    4. We fetch the user from the database by ID.
    """

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        # This header tells the client that Bearer auth is required.
        # It's part of the HTTP auth spec (RFC 7235).
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )

        user_id = payload.get("sub")

        if user_id is None:
            raise credentials_exception

    except JWTError:
        raise credentials_exception

    user = db.get(User, user_id)

    if user is None:
        raise credentials_exception

    return user


def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Ensure the authenticated user account is active.

    This is a SECOND layer on top of get_current_user. It adds
    business rules even if the token itself is valid.

    In your routes, prefer this dependency over get_current_user
    to enforce the is_active constraint consistently.
    """

    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user account",
        )

    return current_user