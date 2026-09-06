"""add job timestamp defaults

Revision ID: 20260906_0002
Revises: e01dc820a5f5
Create Date: 2026-09-06
"""

import sqlalchemy as sa

from alembic import op


revision = "20260906_0002"
down_revision = "e01dc820a5f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("jobs", "created_at", server_default=sa.text("now()"))
    op.alter_column("jobs", "updated_at", server_default=sa.text("now()"))


def downgrade() -> None:
    op.alter_column("jobs", "updated_at", server_default=None)
    op.alter_column("jobs", "created_at", server_default=None)
