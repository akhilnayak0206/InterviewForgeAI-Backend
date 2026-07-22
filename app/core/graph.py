"""
Shared LangGraph checkpointer and graph registry.

This module owns the PostgreSQL checkpointer connection pool and
provides FastAPI dependencies for accessing compiled workflow graphs.
"""
import re

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.core.config import settings
from app.workflows.interview_graph import build_interview_workflow


def _pg_conn_string(url: str) -> str:
    """Strip SQLAlchemy dialect suffixes so psycopg can use the URL."""
    return re.sub(r"^postgresql\+\w+://", "postgresql://", url)


# Module-level shared checkpointer and graph registry (initialized in main.py lifespan)
_checkpointer_cm = None
_checkpointer = None
_graphs: dict[str, object] = {}


async def init_checkpointer():
    """
    Initialize the shared PostgreSQL checkpointer and register all workflow graphs.

    Call this from FastAPI lifespan during startup.
    """
    global _checkpointer_cm, _checkpointer, _graphs

    conn_string = _pg_conn_string(settings.DATABASE_URL)
    _checkpointer_cm = AsyncPostgresSaver.from_conn_string(conn_string)
    _checkpointer = await _checkpointer_cm.__aenter__()
    await _checkpointer.setup()
    print("PostgreSQL checkpointer initialized")

    # Register all workflow graphs here
    _graphs["interview"] = build_interview_workflow().compile(checkpointer=_checkpointer)
    print(f"Registered {len(_graphs)} workflow graph(s)")


async def close_checkpointer():
    """
    Close the shared checkpointer connection pool.

    Call this from FastAPI lifespan during shutdown.
    """
    global _checkpointer_cm, _checkpointer, _graphs

    if _checkpointer_cm is not None:
        await _checkpointer_cm.__aexit__(None, None, None)
        _checkpointer_cm = None
        _checkpointer = None
        _graphs = {}


def get_graph(name: str):
    """
    FastAPI dependency that returns a compiled graph by name.

    Args:
        name: Graph name (e.g., "interview")

    Raises:
        RuntimeError: If checkpointer not initialized or graph not found
    """
    if _checkpointer is None:
        raise RuntimeError("Checkpointer not initialized. Check server logs.")
    if name not in _graphs:
        raise RuntimeError(f"Graph '{name}' not registered. Available: {list(_graphs.keys())}")
    return _graphs[name]


def get_interview_graph():
    """FastAPI dependency that returns the interview graph."""
    return get_graph("interview")