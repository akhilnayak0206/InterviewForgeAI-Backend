"""Database session factory."""
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session

from app.core.database import engine

SessionLocal = sessionmaker(
    bind=engine,
    class_=Session,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


def get_db():
    """Yield one database session per request."""
    with SessionLocal() as db:
        yield db
