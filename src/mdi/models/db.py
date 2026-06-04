"""SQLAlchemy ORM models — tables and row-level-security policies.

Every tenant-scoped table carries a `tenant_id` column and is filtered by
RLS using `current_setting('app.tenant_id')`. The actual policies are
created by the alembic migration; the ORM just declares the columns.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, ClassVar

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    MappedAsDataclass,
    mapped_column,
)


class Base(MappedAsDataclass, DeclarativeBase, kw_only=True):
    """Common base — pgvector type registers automatically when models are imported."""

    # ClassVar tells the dataclass machinery this is not a field — and
    # tells ruff (RUF012) it's intentionally a mutable class-level mapping.
    type_annotation_map: ClassVar[dict[Any, Any]] = {
        dict[str, Any]: JSONB,
        list[str]: ARRAY(Text),
    }


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default_factory=uuid.uuid4)


def _tenant_fk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


def _utcnow() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), default=None)


# ---------------------------------------------------------------------------
# Tenant + auth
# ---------------------------------------------------------------------------
class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = _uuid_pk()
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    monthly_cost_cap_usd: Mapped[float] = mapped_column(Float, default=200.0)
    cost_override_active: Mapped[bool] = mapped_column(Boolean, default=False)
    pack_slug: Mapped[str | None] = mapped_column(
        String(64), default=None, nullable=True,
    )
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default_factory=dict)
    created_at: Mapped[datetime] = _utcnow()


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    key_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(128), default="default")
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, nullable=True,
    )
    created_at: Mapped[datetime] = _utcnow()


# ---------------------------------------------------------------------------
# Packs (optional vertical specialization)
# ---------------------------------------------------------------------------
class Pack(Base):
    __tablename__ = "packs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str] = mapped_column(String(32), default="1.0.0")
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, default_factory=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _utcnow()

    __table_args__ = (UniqueConstraint("slug", "version", name="uq_pack_slug_version"),)


# ---------------------------------------------------------------------------
# Documents + extractions
# ---------------------------------------------------------------------------
class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), default=None, nullable=True, index=True,
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), default="application/octet-stream")
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    storage_uri: Mapped[str | None] = mapped_column(Text, default=None, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True, index=True)
    cluster: Mapped[dict[str, Any]] = mapped_column(JSONB, default_factory=dict)
    layout: Mapped[str | None] = mapped_column(String(32), default=None, nullable=True)
    created_at: Mapped[datetime] = _utcnow()


class Extraction(Base):
    __tablename__ = "extractions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    fields: Mapped[dict[str, Any]] = mapped_column(JSONB, default_factory=dict)
    field_confidences: Mapped[dict[str, Any]] = mapped_column(JSONB, default_factory=dict)
    field_provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, default_factory=dict)
    extraction_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = _utcnow()


# ---------------------------------------------------------------------------
# Pattern Cortex / Hippocampus memory
# ---------------------------------------------------------------------------
class Pattern(Base):
    """A learned (industry, vendor, doc_type) pattern with discovered schema."""

    __tablename__ = "patterns"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    industry: Mapped[str] = mapped_column(String(128), nullable=False)
    vendor: Mapped[str] = mapped_column(String(255), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(128), nullable=False)
    schema_def: Mapped[dict[str, Any]] = mapped_column(JSONB, default_factory=dict)
    rules: Mapped[dict[str, Any]] = mapped_column(JSONB, default_factory=dict)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(1024), default=None, nullable=True,
    )
    seen_count: Mapped[int] = mapped_column(Integer, default=1)
    last_seen_at: Mapped[datetime] = _utcnow()
    created_at: Mapped[datetime] = _utcnow()

    __table_args__ = (
        Index("ix_patterns_scope", "tenant_id", "industry", "vendor", "doc_type"),
        UniqueConstraint(
            "tenant_id", "industry", "vendor", "doc_type",
            name="uq_patterns_scope",
        ),
    )


class Correction(Base):
    """Analyst-supplied correction; replays into Hands prompt for matching scope."""

    __tablename__ = "corrections"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    industry: Mapped[str] = mapped_column(String(128), nullable=False)
    vendor: Mapped[str] = mapped_column(String(255), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(128), nullable=False)
    field_path: Mapped[str] = mapped_column(String(512), nullable=False)
    extracted_value: Mapped[str | None] = mapped_column(Text, default=None, nullable=True)
    corrected_value: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, default=None, nullable=True)
    agreement_count: Mapped[int] = mapped_column(Integer, default=1)
    last_applied_at: Mapped[datetime] = _utcnow()
    created_at: Mapped[datetime] = _utcnow()

    __table_args__ = (
        Index("ix_corrections_scope", "tenant_id", "industry", "vendor", "doc_type"),
    )


# ---------------------------------------------------------------------------
# Conscience anomalies
# ---------------------------------------------------------------------------
class Anomaly(Base):
    __tablename__ = "anomalies"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"),
        default=None, nullable=True, index=True,
    )
    rule_id: Mapped[str] = mapped_column(String(255), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), default="MEDIUM")
    field_path: Mapped[str | None] = mapped_column(String(512), default=None, nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, default_factory=dict)
    invented: Mapped[bool] = mapped_column(Boolean, default=False)
    accepted_by_analyst: Mapped[bool | None] = mapped_column(
        Boolean, default=None, nullable=True,
    )
    created_at: Mapped[datetime] = _utcnow()

    __table_args__ = (
        CheckConstraint(
            "severity IN ('HIGH', 'MEDIUM', 'LOW', 'INFO')",
            name="ck_anomaly_severity",
        ),
    )


# ---------------------------------------------------------------------------
# Knowledge Graph (Postgres-backed; NetworkX-compatible API in brain/knowledge_graph.py)
# ---------------------------------------------------------------------------
class KGNode(Base):
    __tablename__ = "kg_nodes"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    node_type: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_key: Mapped[str] = mapped_column(String(512), nullable=False)
    properties: Mapped[dict[str, Any]] = mapped_column(JSONB, default_factory=dict)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), default_factory=list)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = _utcnow()

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "node_type", "canonical_key",
            name="uq_kg_node_scope",
        ),
        Index("ix_kg_nodes_lookup", "tenant_id", "node_type"),
        CheckConstraint(
            "node_type IN ("
            "'Vendor','Customer','Account','Contract','Document','Patient',"
            "'Provider','PurchaseOrder','Phone','Address','Employee','Generic'"
            ")",
            name="ck_kg_node_type",
        ),
    )


class KGEdge(Base):
    __tablename__ = "kg_edges"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    src_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("kg_nodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    dst_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("kg_nodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    edge_type: Mapped[str] = mapped_column(String(64), nullable=False)
    properties: Mapped[dict[str, Any]] = mapped_column(JSONB, default_factory=dict)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = _utcnow()

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "src_id", "dst_id", "edge_type",
            name="uq_kg_edge_scope",
        ),
        CheckConstraint(
            "edge_type IN ("
            "'BILLED_BY','BELONGS_TO_CUSTOMER','INVOICE_FOR','GOVERNED_BY',"
            "'REFERENCES','TREATED_BY','FULFILLS','RESIDES_AT',"
            "'CONTACTABLE_AT','EMPLOYED_BY','GENERIC_LINK'"
            ")",
            name="ck_kg_edge_type",
        ),
    )


# ---------------------------------------------------------------------------
# Audit + cost
# ---------------------------------------------------------------------------
class AuditEvent(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    object_type: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True)
    object_id: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default_factory=dict)
    created_at: Mapped[datetime] = _utcnow()

    __table_args__ = (
        Index("ix_audit_log_lookup", "tenant_id", "object_type", "object_id"),
    )


class CostEvent(Base):
    __tablename__ = "cost_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
        index=True,
    )
    organ: Mapped[str] = mapped_column(String(64), default="unknown")
    model: Mapped[str] = mapped_column(String(64), default="unknown")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    request_id: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True)
    created_at: Mapped[datetime] = _utcnow()


# ---------------------------------------------------------------------------
# Batch + report
# ---------------------------------------------------------------------------
class Batch(Base):
    __tablename__ = "batches"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    status: Mapped[str] = mapped_column(String(32), default="pending")
    total_documents: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = _utcnow()
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, nullable=True,
    )
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    report: Mapped[dict[str, Any]] = mapped_column(JSONB, default_factory=dict)


class DocChunk(Base):
    """RAG chunk store — one row per ~512-token slice of an ingested document.

    The Chat layer queries this by cosine similarity over `embedding` to
    retrieve grounding context for synthesis questions. Memory hits on the
    `patterns` table are still the cluster-level fast path; doc_chunks
    fires only when Chat needs the document's actual text.
    """

    __tablename__ = "doc_chunks"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_idx: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(1024), default=None, nullable=True,
    )
    created_at: Mapped[datetime] = _utcnow()

    __table_args__ = (
        UniqueConstraint("document_id", "chunk_idx", name="uq_doc_chunk_idx"),
    )


class EntityMergeProposal(Base):
    """Queue of review-tier entity-resolution proposals awaiting analyst decision.

    Graph Builder upserts pending rows here when rapidfuzz scores fall
    between the review threshold (80) and the auto-merge threshold (85).
    Analysts approve or reject from the Audit tab; rejected pairs are
    consulted by future Graph Builder runs to avoid re-proposing.
    """

    __tablename__ = "entity_merge_proposals"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    node_type: Mapped[str] = mapped_column(String(64), nullable=False)
    proposed_key: Mapped[str] = mapped_column(String(512), nullable=False)
    matched_key: Mapped[str] = mapped_column(String(512), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    decided_by: Mapped[str | None] = mapped_column(
        String(255), default=None, nullable=True,
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, nullable=True,
    )
    created_at: Mapped[datetime] = _utcnow()

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="ck_merge_proposal_status",
        ),
        UniqueConstraint(
            "tenant_id", "node_type", "proposed_key", "matched_key",
            name="uq_merge_proposal_pair",
        ),
        Index(
            "ix_merge_proposals_tenant_status",
            "tenant_id", "status",
        ),
    )


# Tables that need RLS policies in the migration:
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
    "doc_chunks",
    "entity_merge_proposals",
)
