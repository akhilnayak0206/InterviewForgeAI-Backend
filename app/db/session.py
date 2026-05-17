"""Database session factory."""
from sqlalchemy.orm import sessionmaker

from app.core.database import engine

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
)


def get_db():
    """Get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
