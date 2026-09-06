"""Redis key namespace builders.

Centralizing key construction prevents:
    - Typos (hardcoded strings in routes/services)
    - Collisions (two features using the same key pattern)
    - Security gaps (forgetting user_id in a cache key)

Key format convention:
    {namespace}:{resource}:{identifier}

    namespace  = what the key is for (cache, ratelimit, lock)
    resource   = what type of thing (session, user, embed)
    identifier = unique ID (UUID, user_id, IP address)

Examples:
    cache:session:abc-123
    cache:rag:user-456:resume:hash-789:v1
    ratelimit:user:user-456:chat
    ratelimit:ip:192.168.1.1:auth
    lock:embed:doc-789
"""

from __future__ import annotations

import hashlib
import uuid

# — Cache Keys —


def cache_session_key(session_id: uuid.UUID) -> str:
    """Key for a cached interview session."""
    return f"cache:session:{session_id}"


def cache_user_key(user_id: uuid.UUID) -> str:
    """Key for cached user profile data."""
    return f"cache:user:{user_id}"


def cache_rag_key(
    *,
    user_id: uuid.UUID,
    query: str,
    document_type: str | None = None,
    embedding_version: str = "v1",
) -> str:
    """Key for cached RAG retrieval results.

    The query is hashed because:
        1. Queries can be long (exceeding practical key lengths)
        2. We only want exact-match caching (not fuzzy)
        3. Hash collisions are astronomically unlikely with SHA-256

    user_id is included for tenant isolation — User A's results
    must NEVER be served to User B.
    """
    query_hash = hashlib.sha256(query.strip().lower().encode()).hexdigest()[:16]
    doc_type = document_type or "all"
    return f"cache:rag:{user_id}:{doc_type}:{query_hash}:{embedding_version}"


def cache_rag_pattern(user_id: uuid.UUID) -> str:
    """Pattern matching ALL RAG cache keys for a user.

    Used for bulk invalidation when a user's documents are re-embedded.
    WARNING: Use with SCAN, never with KEYS in production.
    """
    return f"cache:rag:{user_id}:*"


# — Rate Limit Keys —


def rate_limit_key(user_id: uuid.UUID, action: str) -> str:
    """Key for per-user rate limiting.

    action examples: "chat", "embed", "workflow"
    """
    return f"ratelimit:user:{user_id}:{action}"


def rate_limit_ip_key(ip: str, action: str) -> str:
    """Key for per-IP rate limiting.

    Used for unauthenticated endpoints (login, register).
    """
    return f"ratelimit:ip:{ip}:{action}"


# — Lock Keys —


def lock_key(resource: str, resource_id: uuid.UUID) -> str:
    """Key for a distributed lock.

    resource examples: "embed", "report"

    Lock on embedding document abc-123:
        lock:embed:abc-123

    Lock on generating report for session xyz-789:
        lock:report:xyz-789
    """
    return f"lock:{resource}:{resource_id}"
