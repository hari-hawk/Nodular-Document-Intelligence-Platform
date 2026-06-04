"""corrections.embedding — pgvector column for semantic correction recall

Revision ID: 0006_correction_embeddings
Revises: 0005_auto_pack_proposals
Create Date: 2026-06-04

Wave 2.3 of the DD uplift. Today, Hippocampus.get_corrections() does
EXACT matching by (industry, vendor, doc_type) — which means an analyst
correction on an "AT&T invoice" never surfaces for a new "AT&T Business
Services invoice" even though they're the same vendor with different
emissions from Eyes.

Digital-Direction solved this with embeddings on the corrections table:
build a sentence like "vendor=AT&T doc_type=invoice field=total
extracted=$3054.08 corrected=$3054.10" and store its embedding. Then
two-tier recall: exact match first, then add semantic neighbours from
pgvector ANN.

This migration adds:
  - corrections.embedding (vector(1024), nullable — old rows have no
    embedding until a backfill runs)
  - HNSW index on the embedding column for cosine ANN
  - mdi_app GRANT (re-applied; column inherits but explicit is safer)
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0006_correction_embeddings"
down_revision = "0005_auto_pack_proposals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # bge-m3 emits 1024-dim vectors; matches the existing patterns +
    # doc_chunks columns so a single embedder serves everything.
    op.add_column(
        "corrections",
        sa.Column("embedding", Vector(1024), nullable=True),
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_corrections_embedding_hnsw "
        "ON corrections USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )
    # Belt-and-braces: re-grant on the table — added columns inherit
    # the table's grants, but if the role was ever revoked we want
    # the GRANT explicit.
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON corrections TO mdi_app"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_corrections_embedding_hnsw")
    op.drop_column("corrections", "embedding")
