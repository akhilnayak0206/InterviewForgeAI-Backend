"""docuemnt chunk rag

Revision ID: cd487927612b
Revises: d2e8b7c5a1f4
Create Date: 2026-08-30 09:16:53.542804+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "d2e8b7c5a1f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Step 1: Enable pgvector extension.
    # This adds the 'vector' type to PostgreSQL.
    # Requires: CREATE EXTENSION privilege (superuser or granted).
    # IF NOT EXISTS makes this idempotent - safe to run multiple times.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Step 2: Create the document_chunks table.
    op.create_table(
        "document_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("document_type", sa.String(length=32), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        # pgvector's vector type - 1024 floats stored as a compact binary array.
        sa.Column("embedding", Vector(1024), nullable=False),
        sa.Column("embedding_model", sa.String(length=128), nullable=False),
        sa.Column("embedding_version", sa.String(length=32), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("metadata", postgresql.JSON(), nullable=True),
        # Foreign keys
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_chunks_document_id_documents"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_document_chunks_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["interview_sessions.id"],
            name=op.f("fk_document_chunks_session_id_interview_sessions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_chunks")),
    )

    # Step 3: Create standard B-tree indexes for filtering.
    op.create_index(
        op.f("ix_document_chunks_document_id"),
        "document_chunks",
        ["document_id"],
    )

    op.create_index(
        op.f("ix_document_chunks_user_id"),
        "document_chunks",
        ["user_id"],
    )

    op.create_index(
        op.f("ix_document_chunks_session_id"),
        "document_chunks",
        ["session_id"],
    )

    op.create_index(
        op.f("ix_document_chunks_document_type"),
        "document_chunks",
        ["document_type"],
    )

    # Composite indexes for common query patterns.
    op.create_index(
        "ix_document_chunks_user_type",
        "document_chunks",
        ["user_id", "document_type"],
    )

    op.create_index(
        "ix_document_chunks_document_order",
        "document_chunks",
        ["document_id", "chunk_index"],
    )

    # Step 4: Create HNSW vector index.
    # This is the key index that makes vector search fast.
    #
    # HNSW parameters:
    #   m = 16              - Number of connections per node in the graph.
    #                         Higher = better recall, more memory. 16 is the default.
    #   ef_construction = 64 - Search width during index construction.
    #                         Higher = better index quality, slower build. 64 is default.
    #
    # vector_cosine_ops - Use cosine distance for similarity.
    #
    # For your scale (thousands of chunks), this index is instant to build
    # and gives ~99% recall on similarity queries.
    op.execute(
        """
        CREATE INDEX ix_document_chunks_embedding_hnsw
        ON document_chunks
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )


def downgrade() -> None:
    op.drop_index("ix_document_chunks_embedding_hnsw", table_name="document_chunks")
    op.drop_index("ix_document_chunks_document_order", table_name="document_chunks")
    op.drop_index("ix_document_chunks_user_type", table_name="document_chunks")
    op.drop_index(op.f("ix_document_chunks_document_type"), table_name="document_chunks")
    op.drop_index(op.f("ix_document_chunks_session_id"), table_name="document_chunks")
    op.drop_index(op.f("ix_document_chunks_user_id"), table_name="document_chunks")
    op.drop_index(op.f("ix_document_chunks_document_id"), table_name="document_chunks")
    op.drop_table("document_chunks")
    # Note: We do NOT drop the pgvector extension in downgrade.
    # Other tables or extensions might depend on it.
