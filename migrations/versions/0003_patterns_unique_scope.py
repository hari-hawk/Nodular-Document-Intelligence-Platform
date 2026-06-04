"""dedup patterns + add unique scope constraint

Revision ID: 0003_patterns_unique
Revises: 0002_doc_chunks
Create Date: 2026-05-13

Why: Hippocampus.write_pattern used INSERT-not-UPSERT, so parallel batches
processing identical (industry, vendor, doc_type) created duplicate rows.
After this migration the same scope can only appear once per tenant; the
ORM switches to ON CONFLICT DO UPDATE.
"""
from __future__ import annotations

from alembic import op

revision = "0003_patterns_unique"
down_revision = "0002_doc_chunks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Collapse duplicates first — keep the row with the highest seen_count;
    # tiebreak by most recent last_seen_at.
    op.execute(
        """
        DELETE FROM patterns p
        USING patterns q
        WHERE p.tenant_id = q.tenant_id
          AND p.industry  = q.industry
          AND p.vendor    = q.vendor
          AND p.doc_type  = q.doc_type
          AND (
            p.seen_count < q.seen_count
            OR (p.seen_count = q.seen_count AND p.last_seen_at < q.last_seen_at)
            OR (p.seen_count = q.seen_count AND p.last_seen_at = q.last_seen_at AND p.id > q.id)
          )
        """
    )
    op.create_unique_constraint(
        "uq_patterns_scope",
        "patterns",
        ["tenant_id", "industry", "vendor", "doc_type"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_patterns_scope", "patterns", type_="unique")
