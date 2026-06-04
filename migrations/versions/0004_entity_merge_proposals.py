"""entity_merge_proposals — actionable queue for review-tier KG merges

Revision ID: 0004_merge_proposals
Revises: 0003_patterns_unique
Create Date: 2026-05-19

The Entity Resolver inside Graph Builder already audit-logs review-tier
proposals (score 80-84, between the auto-merge threshold and the
keep-separate floor). This table makes those proposals queryable as a
QUEUE so analysts can approve or reject them from the Audit tab.

  audit_log = history (append-only, what happened)
  entity_merge_proposals = state (what's still pending)

Lifecycle:
  pending -> approved  (KG merge executed, source node deleted)
  pending -> rejected  (future Graph Builder calls won't re-propose)
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0004_merge_proposals"
down_revision = "0003_patterns_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "entity_merge_proposals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_type", sa.String(64), nullable=False),
        sa.Column("proposed_key", sa.String(512), nullable=False),  # the new variant
        sa.Column("matched_key", sa.String(512), nullable=False),   # the existing keeper
        sa.Column("score", sa.Float, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("decided_by", sa.String(255), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="ck_merge_proposal_status",
        ),
        # The same (proposed, matched) pair shouldn't accumulate duplicate
        # pending rows — Graph Builder upserts.
        sa.UniqueConstraint(
            "tenant_id", "node_type", "proposed_key", "matched_key",
            name="uq_merge_proposal_pair",
        ),
    )
    op.create_index(
        "ix_merge_proposals_tenant_status",
        "entity_merge_proposals", ["tenant_id", "status"],
    )

    # RLS — same pattern as every other tenant-scoped table.
    op.execute("ALTER TABLE entity_merge_proposals ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE entity_merge_proposals FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON entity_merge_proposals
        USING (
            tenant_id::text = NULLIF(current_setting('app.tenant_id', true), '')
        )
        WITH CHECK (
            tenant_id::text = NULLIF(current_setting('app.tenant_id', true), '')
        )
        """
    )
    # Runtime app role needs CRUD on the new table.
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON entity_merge_proposals TO mdi_app"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON entity_merge_proposals")
    op.execute("ALTER TABLE entity_merge_proposals DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_merge_proposals_tenant_status",
                  table_name="entity_merge_proposals")
    op.drop_table("entity_merge_proposals")
