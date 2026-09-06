"""create jobs table

Revision ID: e01dc820a5f5
Revises: a1b2c3d4e5f6
Create Date: 2026-09-06 13:52:24.838160+00:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "e01dc820a5f5"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create jobs table
    op.create_table(
        "jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "job_type",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "payload",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "result",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "error",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "progress",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "progress_message",
            sa.String(length=256),
            nullable=True,
        ),
        sa.Column(
            "attempts",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "max_attempts",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        op.f("ix_jobs_job_type"),
        "jobs",
        ["job_type"],
        unique=False,
    )

    op.create_index(
        op.f("ix_jobs_status"),
        "jobs",
        ["status"],
        unique=False,
    )

    op.create_index(
        op.f("ix_jobs_user_id"),
        "jobs",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_jobs_user_id"),
        table_name="jobs",
    )

    op.drop_index(
        op.f("ix_jobs_status"),
        table_name="jobs",
    )

    op.drop_index(
        op.f("ix_jobs_job_type"),
        table_name="jobs",
    )

    op.drop_table("jobs")
