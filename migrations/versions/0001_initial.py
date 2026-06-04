"""initial schema with row-level security

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-07
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from pgvector.sqlalchemy import Vector

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

RLS_TABLES = (
    "api_keys",
    "documents",
    "extractions",
    "patterns",
    "corrections",
    "anomalies",
    "kg_nodes",
    "kg_edges",
    "audit_log",
    "batches",
)


def upgrade() -> None:
    # Extensions (idempotent — also bootstrapped by docker-entrypoint init script).
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "tenants",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("slug", sa.String(64), unique=True, nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("monthly_cost_cap_usd", sa.Float, nullable=False, server_default="200.0"),
        sa.Column("cost_override_active", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("pack_slug", sa.String(64), nullable=True),
        sa.Column("config", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "api_keys",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key_hash", sa.String(255), nullable=False, unique=True),
        sa.Column("label", sa.String(128), nullable=False, server_default="default"),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "packs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("version", sa.String(32), nullable=False, server_default="1.0.0"),
        sa.Column("manifest", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("slug", "version", name="uq_pack_slug_version"),
    )

    op.create_table(
        "documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("batch_id", UUID(as_uuid=True), nullable=True),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False, server_default="application/octet-stream"),
        sa.Column("page_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("bytes", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("storage_uri", sa.Text, nullable=True),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("cluster", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("layout", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_documents_tenant_id", "documents", ["tenant_id"])
    op.create_index("ix_documents_batch_id", "documents", ["batch_id"])
    op.create_index("ix_documents_sha256", "documents", ["sha256"])

    op.create_table(
        "extractions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("fields", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("field_confidences", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("field_provenance", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("extraction_cost_usd", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_extractions_tenant_id", "extractions", ["tenant_id"])
    op.create_index("ix_extractions_document_id", "extractions", ["document_id"])

    op.create_table(
        "patterns",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("industry", sa.String(128), nullable=False),
        sa.Column("vendor", sa.String(255), nullable=False),
        sa.Column("doc_type", sa.String(128), nullable=False),
        sa.Column("schema_def", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("rules", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("seen_count", sa.Integer, nullable=False, server_default="1"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_patterns_tenant_id", "patterns", ["tenant_id"])
    op.create_index("ix_patterns_scope", "patterns", ["tenant_id", "industry", "vendor", "doc_type"])
    # HNSW vector index — cosine distance ops.
    op.execute(
        "CREATE INDEX ix_patterns_embedding_hnsw ON patterns "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )

    op.create_table(
        "corrections",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("industry", sa.String(128), nullable=False),
        sa.Column("vendor", sa.String(255), nullable=False),
        sa.Column("doc_type", sa.String(128), nullable=False),
        sa.Column("field_path", sa.String(512), nullable=False),
        sa.Column("extracted_value", sa.Text, nullable=True),
        sa.Column("corrected_value", sa.Text, nullable=False),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("agreement_count", sa.Integer, nullable=False, server_default="1"),
        sa.Column("last_applied_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_corrections_tenant_id", "corrections", ["tenant_id"])
    op.create_index("ix_corrections_scope", "corrections", ["tenant_id", "industry", "vendor", "doc_type"])

    op.create_table(
        "anomalies",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=True),
        sa.Column("rule_id", sa.String(255), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False, server_default="MEDIUM"),
        sa.Column("field_path", sa.String(512), nullable=True),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("context", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("invented", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("accepted_by_analyst", sa.Boolean, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("severity IN ('HIGH', 'MEDIUM', 'LOW', 'INFO')", name="ck_anomaly_severity"),
    )
    op.create_index("ix_anomalies_tenant_id", "anomalies", ["tenant_id"])
    op.create_index("ix_anomalies_document_id", "anomalies", ["document_id"])

    op.create_table(
        "kg_nodes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_type", sa.String(64), nullable=False),
        sa.Column("canonical_key", sa.String(512), nullable=False),
        sa.Column("properties", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("aliases", ARRAY(sa.Text), nullable=False, server_default=sa.text("'{}'::text[]")),
        sa.Column("confidence", sa.Float, nullable=False, server_default="1.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "node_type", "canonical_key", name="uq_kg_node_scope"),
        sa.CheckConstraint(
            "node_type IN ("
            "'Vendor','Customer','Account','Contract','Document','Patient',"
            "'Provider','PurchaseOrder','Phone','Address','Employee','Generic'"
            ")",
            name="ck_kg_node_type",
        ),
    )
    op.create_index("ix_kg_nodes_tenant_id", "kg_nodes", ["tenant_id"])
    op.create_index("ix_kg_nodes_lookup", "kg_nodes", ["tenant_id", "node_type"])

    op.create_table(
        "kg_edges",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("src_id", UUID(as_uuid=True), sa.ForeignKey("kg_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dst_id", UUID(as_uuid=True), sa.ForeignKey("kg_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("edge_type", sa.String(64), nullable=False),
        sa.Column("properties", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("confidence", sa.Float, nullable=False, server_default="1.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "src_id", "dst_id", "edge_type", name="uq_kg_edge_scope"),
        sa.CheckConstraint(
            "edge_type IN ("
            "'BILLED_BY','BELONGS_TO_CUSTOMER','INVOICE_FOR','GOVERNED_BY',"
            "'REFERENCES','TREATED_BY','FULFILLS','RESIDES_AT',"
            "'CONTACTABLE_AT','EMPLOYED_BY','GENERIC_LINK'"
            ")",
            name="ck_kg_edge_type",
        ),
    )
    op.create_index("ix_kg_edges_tenant_id", "kg_edges", ["tenant_id"])
    op.create_index("ix_kg_edges_src", "kg_edges", ["src_id"])
    op.create_index("ix_kg_edges_dst", "kg_edges", ["dst_id"])

    op.create_table(
        "audit_log",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("object_type", sa.String(64), nullable=True),
        sa.Column("object_id", sa.String(64), nullable=True),
        sa.Column("payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_audit_log_tenant_id", "audit_log", ["tenant_id"])
    op.create_index("ix_audit_log_lookup", "audit_log", ["tenant_id", "object_type", "object_id"])

    op.create_table(
        "cost_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True),
        sa.Column("organ", sa.String(64), nullable=False, server_default="unknown"),
        sa.Column("model", sa.String(64), nullable=False, server_default="unknown"),
        sa.Column("input_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_cost_events_tenant_id", "cost_events", ["tenant_id"])

    op.create_table(
        "batches",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("total_documents", sa.Integer, nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cost_usd", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("report", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index("ix_batches_tenant_id", "batches", ["tenant_id"])

    # ---- Row-level security ----------------------------------------------
    # Every tenant-scoped table is filtered by current_setting('app.tenant_id').
    # If the GUC is missing or empty, no rows are visible.
    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (
                tenant_id::text = NULLIF(current_setting('app.tenant_id', true), '')
            )
            WITH CHECK (
                tenant_id::text = NULLIF(current_setting('app.tenant_id', true), '')
            )
            """
        )


def downgrade() -> None:
    for table in RLS_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.drop_table("batches")
    op.drop_table("cost_events")
    op.drop_table("audit_log")
    op.drop_table("kg_edges")
    op.drop_table("kg_nodes")
    op.drop_table("anomalies")
    op.drop_table("corrections")
    op.execute("DROP INDEX IF EXISTS ix_patterns_embedding_hnsw")
    op.drop_table("patterns")
    op.drop_table("extractions")
    op.drop_table("documents")
    op.drop_table("packs")
    op.drop_table("api_keys")
    op.drop_table("tenants")
