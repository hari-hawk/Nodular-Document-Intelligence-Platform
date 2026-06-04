"""doc_chunks table for RAG retrieval

Revision ID: 0002_doc_chunks
Revises: 0001_initial
Create Date: 2026-05-13
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from pgvector.sqlalchemy import Vector

revision = "0002_doc_chunks"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "doc_chunks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", UUID(as_uuid=True),
                  sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_idx", sa.Integer, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("token_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("document_id", "chunk_idx", name="uq_doc_chunk_idx"),
    )
    op.create_index("ix_doc_chunks_tenant_id", "doc_chunks", ["tenant_id"])
    op.create_index("ix_doc_chunks_document_id", "doc_chunks", ["document_id"])
    op.execute(
        "CREATE INDEX ix_doc_chunks_embedding_hnsw ON doc_chunks "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )

    # RLS — same pattern as every other tenant-scoped table.
    op.execute("ALTER TABLE doc_chunks ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE doc_chunks FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON doc_chunks
        USING (
            tenant_id::text = NULLIF(current_setting('app.tenant_id', true), '')
        )
        WITH CHECK (
            tenant_id::text = NULLIF(current_setting('app.tenant_id', true), '')
        )
        """
    )

    # Re-grant mdi_app perms on the new table (DEFAULT PRIVILEGES handles future
    # tables, but this migration runs as `mdi` so the grant happens here too).
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON doc_chunks TO mdi_app"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON doc_chunks")
    op.execute("ALTER TABLE doc_chunks DISABLE ROW LEVEL SECURITY")
    op.execute("DROP INDEX IF EXISTS ix_doc_chunks_embedding_hnsw")
    op.drop_table("doc_chunks")
