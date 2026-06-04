"""tenant_facts — per-tenant persistent knowledge store (Wave 2.4)

Revision ID: 0007_tenant_facts
Revises: 0006_correction_embeddings
Create Date: 2026-06-04

Today every batch extracts in isolation. The same customer uploads new
invoices each month and we re-extract from scratch — we never carry
forward "AT&T account 0133442501 is owned by Globex Inc." or "MSA
2024-09 expires 2026-03-31" or "the customer's preferred billing
address is X." That's wasted re-discovery, AND it makes us less
confident than we should be on stable facts.

Digital-Direction's `master_data.py` keeps a per-client knowledge
store. This is the MDI port — RLS-isolated per tenant, free-form fact
KV with a fact_type tag so analysts can filter ("show me everything
the brain knows about Globex Inc.'s contracts").

Schema:
  (tenant_id, fact_type, key) → value, confidence, source_doc_id,
                                last_seen_at, sighting_count

  fact_type is a free-form string but conventionally one of:
    account → vendor              (e.g. "0133442501" → "AT&T")
    contract → expiration         (e.g. "MSA-2024-09" → "2026-03-31")
    vendor → address              (e.g. "AT&T" → "208 S. Akard, Dallas")
    customer → preferred_terms    (e.g. "Globex" → "Net 30")

Unique constraint on (tenant_id, fact_type, key) so subsequent
sightings UPSERT — bumping sighting_count and refreshing last_seen_at
without overwriting unless the new confidence is strictly higher.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0007_tenant_facts"
down_revision = "0006_correction_embeddings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_facts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("fact_type", sa.String(64), nullable=False),
        sa.Column("key", sa.String(512), nullable=False),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False, server_default="0.5"),
        # Provenance: which document first surfaced this fact.
        sa.Column("source_doc_id", UUID(as_uuid=True), nullable=True),
        sa.Column("sighting_count", sa.Integer, nullable=False, server_default="1"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "tenant_id", "fact_type", "key",
            name="uq_tenant_facts_tenant_type_key",
        ),
    )
    op.create_index(
        "ix_tenant_facts_tenant_type",
        "tenant_facts", ["tenant_id", "fact_type"],
    )
    op.execute("ALTER TABLE tenant_facts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_facts FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_facts_tenant_isolation "
        "ON tenant_facts FOR ALL "
        "USING (tenant_id::text = current_setting('app.tenant_id', true))"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON tenant_facts TO mdi_app"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_facts_tenant_isolation ON tenant_facts")
    op.drop_index("ix_tenant_facts_tenant_type", table_name="tenant_facts")
    op.drop_table("tenant_facts")
