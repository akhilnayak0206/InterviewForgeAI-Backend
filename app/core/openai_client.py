"""
OpenAI Client setup.

This module owns the application's OpenAI client instance — the same
pattern as core/database.py owning the SQLAlchemy engine.

WHY A SINGLE CLIENT INSTANCE:
    The OpenAI SDK uses httpx internally with connection pooling.
    Creating one client and reusing it across requests is efficient —
    it keeps persistent HTTP connections open instead of paying the
    TCP + TLS handshake cost on every API call.

    Creating a new client per request would be like creating a new
    database engine per request — wasteful and unnecessary.

FUTURE:
    When you add streaming, you'll add an AsyncOpenAI client here too.
    When you switch providers, this is the ONLY file that changes.
"""

from openai import OpenAI

from app.core.config import settings

openai_client = OpenAI(
    base_url="https://api.groq.com/openai/v1", api_key=settings.OPENAI_API_KEY
)
