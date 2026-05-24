"""Authentication routes — signup, login, and current-user endpoints.

ENDPOINTS:

POST /auth/signup
    → Register a new account

POST /auth/login
    → Authenticate and receive a JWT

GET /auth/me
    → Get the currently authenticated user's profile


REQUEST FLOW FOR EACH ENDPOINT
================================

SIGNUP FLOW:

Client sends:
    {
        "email": "...",
        "password": "...",
        "full_name": "..."
    }

    ↓

1. Pydantic validates request body
2. user_service.create_user() checks email uniqueness
3. Password is hashed using bcrypt
4. User inserted into PostgreSQL
5. Return safe UserResponse
   (NO password hash, NO token)


LOGIN FLOW:

Client sends FORM DATA (OAuth2 spec):

    username=email@example.com
    password=secret

    ↓

1. OAuth2PasswordRequestForm parses form data
2. authenticate_user() verifies credentials
3. If invalid → 401 Unauthorized
4. If valid → create JWT token
5. Return access token


/ME FLOW:

Client sends header:

    Authorization: Bearer <jwt>

    ↓

1. oauth2_scheme extracts token
2. get_current_user decodes JWT
3. Fetch user from DB
4. get_current_active_user checks is_active
5. Route receives authenticated User object


WHY LOGIN USES FORM DATA (NOT JSON)
===================================

OAuth2PasswordRequestForm follows the OAuth2 standard.

The spec REQUIRES:
    application/x-www-form-urlencoded

FastAPI's Swagger UI automatically understands this format,
which makes the built-in "Authorize" button work correctly.

The field is named "username" by OAuth2 spec,
but we store EMAIL inside that field.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session

from app.core.deps import get_current_active_user
from app.core.security import create_access_token
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import Token
from app.schemas.user import UserCreate, UserResponse
from app.services import user_service

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)


@router.post(
    "/signup",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
)
def signup(
    user_in: UserCreate,
    db: Session = Depends(get_db),
):
    """Create a new user account.

    Reuses user_service.create_user() which already:

        - checks duplicate emails
        - hashes passwords
        - inserts into DB
        - returns created user

    SECURITY CHOICE:
    We intentionally DO NOT return a token on signup.

    The user must explicitly log in afterward.
    """

    return user_service.create_user(
        session=db,
        user_in=user_in,
    )


@router.post(
    "/login",
    response_model=Token,
    summary="Login and receive an access token",
)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """Authenticate user and return JWT token.

    OAuth2PasswordRequestForm fields:

        username -> we store EMAIL here
        password -> plain text password

    Example form data:

        username=user@example.com
        password=secret
    """

    user = user_service.authenticate_user(
        session=db,
        email=form_data.username,  # OAuth2 spec uses "username"
        password=form_data.password,
    )

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # JWT "sub" claim = user ID
    access_token = create_access_token(
        subject=str(user.id),
    )

    return Token(
        access_token=access_token,
    )


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get the currently authenticated user",
)
def get_me(
    current_user: User = Depends(get_current_active_user),
):
    """Return the currently authenticated user's profile.

    Full dependency chain:

        Authorization header
            ↓
        oauth2_scheme extracts token
            ↓
        get_current_user decodes JWT
            ↓
        Fetch user from DB
            ↓
        get_current_active_user validates user
            ↓
        Route receives authenticated User

    FastAPI dependency injection handles everything automatically.
    """

    return current_user