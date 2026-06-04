"""auto_pack_proposals — queue for self-discovered vendor packs

Revision ID: 0005_auto_pack_proposals
Revises: 0004_merge_proposals
Create Date: 2026-06-04

Background (Wave 1.2 of the Digital-Direction uplift):
The Digital-Direction platform auto-registers carriers it has never
seen — when the LLM emits a vendor that isn't in any existing pack,
DD writes a minimal stub so future docs from that vendor route through
generic prompts instead of failing.

MDI's port is more conservative: stubs land in this table as
*proposals*, NOT in the live pack tree. They have zero influence on
extraction until an admin one-click-promotes them via
POST /admin/auto-packs/{id}/promote, which writes the actual stub to
mdi/packs/_auto/<slug>/skills.yaml.

Lifecycle:
  pending  -> approved  (skills.yaml written, vendor starts mattering)
  pending  -> rejected  (future sightings of this slug are ignored)
  pending  -> superseded (a manually-curated pack now covers this vendor)

Why a separate table from entity_merge_proposals: different shape
(vendor-name string, sample extraction blob) and different consumer
(pack registry, not the knowledge graph).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0005_auto_pack_proposals"
down_revision = "0004_merge_proposals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auto_pack_proposals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        # Slugified vendor name — must be stable across sightings of the
        # same vendor so ON CONFLICT collapses repeats into one proposal.
        sa.Column("vendor_slug", sa.String(128), nullable=False),
        # The LLM's verbatim emission. We keep it because the slug strips
        # punctuation/case and we want the original for UI display.
        sa.Column("vendor_name", sa.String(512), nullable=False),
        sa.Column("doc_type_hint", sa.String(64), nullable=True),
        # First document where this vendor was seen — lets analysts open
        # the source PDF to sanity-check the proposal before promoting.
        sa.Column("first_seen_doc_id", UUID(as_uuid=True), nullable=True),
        sa.Column("sample_extraction", JSONB, nullable=True),
        # Count of additional sightings since first detection — useful
        # signal for "this is showing up everywhere, promote it".
        sa.Column("sighting_count", sa.Integer, nullable=False, server_default="1"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("decided_by", sa.String(255), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("promoted_path", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'superseded')",
            name="ck_auto_pack_status",
        ),
        sa.UniqueConstraint(
            "tenant_id", "vendor_slug",
            name="uq_auto_pack_tenant_slug",
        ),
    )
    op.create_index(
        "ix_auto_pack_tenant_status",
        "auto_pack_proposals", ["tenant_id", "status"],
    )
    op.execute("ALTER TABLE auto_pack_proposals ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE auto_pack_proposals FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY auto_pack_proposals_tenant_isolation "
        "ON auto_pack_proposals FOR ALL "
        "USING (tenant_id::text = current_setting('app.tenant_id', true))"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON auto_pack_proposals TO mdi_app"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS auto_pack_proposals_tenant_isolation ON auto_pack_proposals")
    op.drop_index("ix_auto_pack_tenant_status", table_name="auto_pack_proposals")
    op.drop_table("auto_pack_proposals")
