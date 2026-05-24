"""
Core security utilities — password hashing and JWT token management.

This module contains PURE FUNCTIONS with no HTTP or database dependencies.
It is the cryptographic foundation of the auth system.

PASSWORD HASHING (bcrypt via passlib)
- hash_password(plain) -> hashed string
- verify_password(plain, hashed) -> bool
bcrypt automatically handles salting and uses a configurable work factor.

JWT TOKENS (python-jose)
- create_access_token(subject, expires_delta) -> signed JWT string
The token carries the user's identity (sub claim) and is self-contained.

WHY THIS IS SEPARATE FROM ROUTES AND DEPS
These are pure functions — easy to unit test
No FastAPI dependency — reusable from CLI tools, background tasks, etc.
Single source of truth for all crypto operations
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from jose import jwt
import bcrypt

from app.core.config import settings


# --- Password Hashing --------------------------------------------------------

def hash_password(plain_password: str) -> str:
    """Hash a plain-text password using bcrypt.

    Internally, bcrypt:
        1. Generates a random 16-byte salt
        2. Runs the Blowfish cipher for 2^12 (4096) iterations (cost=12)
        3. Produces a 60-character string: $2b$12$salt$hash
    """

    password_bytes = plain_password.encode("utf-8")
    return bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(
    plain_password: str,
    hashed_password: str,
) -> bool:
    """Verify a plain-text password against a stored bcrypt hash.

    How verification works:
        1. Extract the salt from the stored hash
        2. Hash the plain_password with that same salt
        3. Compare the result to the stored hash
        4. Return True if they match

    This is a CONSTANT-TIME comparison (passlib handles this) to prevent
    timing attacks — attackers can't guess the password by measuring
    how long the comparison takes.
    """

    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


# --- JWT Token Creation ------------------------------------------------------


def create_access_token(
    subject: str,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a signed JWT access token.

    Args:
        subject: The "sub" claim. Typically the user's ID as a string.
                 This is the identity the token carries.
        expires_delta: Custom expiration time. Defaults to settings value.

    Token structure (payload before encoding):

        {
            "sub": "user-uuid-string",
            "exp": 1699999999,      # Unix timestamp
            "iat": 1699999399       # Unix timestamp
        }

    The token is signed with HMAC-SHA256 using JWT_SECRET_KEY. Anyone can
    READ the payload (it's just base64), but only the server can VERIFY
    the signature because only the server knows the secret key.
    """

    now = datetime.now(timezone.utc)

    if expires_delta is None:
        expires_delta = timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )

    expire = now + expires_delta

    to_encode = {
        "sub": subject,
        "exp": expire,
        "iat": now,
    }

    return jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
