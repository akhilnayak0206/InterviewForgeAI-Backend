"""Database engine setup.

This module owns the application's SQLAlchemy engine. It intentionally does
not create tables; schema changes are managed by Alembic migrations.
"""
from sqlalchemy import create_engine

from app.core.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    echo=settings.DB_ECHO,
    future=True,
    pool_pre_ping=True,
)
