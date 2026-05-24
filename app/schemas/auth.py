"""Pydantic schemas for authentication endpoints.

Token: The response shape for a successful login.
        Follows the OAuth2 spec: { access_token, token_type }.

NOTE: We do NOT create a "LoginRequest" schema because FastAPI's
      OAuth2PasswordRequestForm already handles the login form parsing.
      The OAuth2 spec requires login credentials to be sent as
      application/x-www-form-urlencoded (form data), not JSON.
"""

from pydantic import BaseModel


class Token(BaseModel):
    """Response returned after successful authentication.

    access_token: The JWT string the client must include in future requests
                  via the Authorization header: "Bearer <token>"
    token_type:   Always "bearer" — tells the client HOW to send the token.
                  This is part of the OAuth2 spec.
    """

    access_token: str
    token_type: str = "bearer"