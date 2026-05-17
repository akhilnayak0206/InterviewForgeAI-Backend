"""SQLModel metadata registration for Alembic.

Alembic imports this module to make sure every table model has been imported
before it compares Python metadata with the live database schema.
"""
from sqlmodel import SQLModel


SQLModel.metadata.naming_convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# Import all SQLModel table classes so they register themselves on
# SQLModel.metadata. Keep this import below the naming convention.
import app.models  # noqa: F401, E402
