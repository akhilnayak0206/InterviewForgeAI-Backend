"""Database engine setup."""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base

from app.core.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    echo=True,
    future=True,
)

Base = declarative_base()
