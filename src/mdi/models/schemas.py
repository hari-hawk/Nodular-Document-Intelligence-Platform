"""Pydantic v2 contracts.

These are the *only* shapes that flow between brain organs and across
layer boundaries. No untyped dict-passing — if a new field is needed,
it goes here first, then the producing organ, then the consumer.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

Severity = Literal["HIGH", "MEDIUM", "LOW", "INFO"]
NodeType = Literal[
    "Vendor", "Customer", "Account", "Contract", "Document",
    "Patient", "Provider", "PurchaseOrder", "Phone", "Address",
    "Employee", "Generic",
]
EdgeType = Literal[
    "BILLED_BY", "BELONGS_TO_CUSTOMER", "INVOICE_FOR", "GOVERNED_BY",
    "REFERENCES", "TREATED_BY", "FULFILLS", "RESIDES_AT",
    "CONTACTABLE_AT", "EMPLOYED_BY", "GENERIC_LINK",
]


class StrictModel(BaseModel):
    """All schemas inherit a strict config — extra fields are rejected."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# ---------------------------------------------------------------------------
# Stage 1 — Ingest
# ---------------------------------------------------------------------------
class IngestedDocument(StrictModel):
    document_id: UUID = Field(default_factory=uuid4)
    filename: str
    mime_type: str
    bytes: int
    page_count: int
    text: str | None = None  # text-extracted; None for vision-only routing
    pages: list[str] = Field(default_factory=list)  # per-page text
    images: list[bytes] = Field(default_factory=list, exclude=True)  # raw bytes for vision
    needs_vision: bool = False
    sha256: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Stage 2 — Eyes (classification)
# ---------------------------------------------------------------------------
class Cluster(StrictModel):
    industry: str
    vendor: str
    doc_type: str
    layout: Literal["tabular", "form", "free_text", "scanned", "mixed"] = "free_text"
    language: str = "en"
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = ""


# ---------------------------------------------------------------------------
# Stages 3, 4 — Hippocampus + Pattern Cortex
# ---------------------------------------------------------------------------
class FieldDef(StrictModel):
    name: str
    type: Literal["string", "number", "date", "currency", "boolean", "list", "object"]
    required: bool = False
    description: str = ""
    examples: list[str] = Field(default_factory=list)


class Schema(StrictModel):
    fields: list[FieldDef] = Field(default_factory=list)
    primary_keys: list[str] = Field(default_factory=list)
    discovered_from: Literal["memory", "discovery", "pack"] = "discovery"
    pack_slug: str | None = None


class Rule(StrictModel):
    rule_id: str
    expression: str  # simpleeval-safe
    severity: Severity = "MEDIUM"
    message: str = ""
    invented: bool = False
    enabled: bool = True


class RuleSet(StrictModel):
    rules: list[Rule] = Field(default_factory=list)
    pattern_id: UUID | None = None


class CorrectionHint(StrictModel):
    field_path: str
    extracted_value: str | None = None
    corrected_value: str
    note: str = ""
    agreement_count: int = 1


class MemoryHit(StrictModel):
    pattern_id: UUID
    similarity: float
    schema_: Schema = Field(alias="schema")
    rules: RuleSet
    corrections: list[CorrectionHint] = Field(default_factory=list)

    @property
    def schema(self) -> Schema:  # type: ignore[override]
        return self.schema_


# ---------------------------------------------------------------------------
# Stage 7 — Hands (extraction)
# ---------------------------------------------------------------------------
class FieldExtraction(StrictModel):
    value: Any
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    source_text: str | None = None
    page: int | None = None


class Extraction(StrictModel):
    document_id: UUID
    fields: dict[str, FieldExtraction] = Field(default_factory=dict)
    cost_usd: float = 0.0
    used_vision: bool = False
    pattern_id: UUID | None = None


# ---------------------------------------------------------------------------
# Stage 8 — Conscience (validation)
# ---------------------------------------------------------------------------
class Anomaly(StrictModel):
    rule_id: str
    severity: Severity
    field_path: str | None = None
    message: str
    invented: bool = False
    context: dict[str, Any] = Field(default_factory=dict)


class ValidationResult(StrictModel):
    document_id: UUID
    anomalies: list[Anomaly] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Stages 10, 11 — Insight Cortex + Inner Voice
# ---------------------------------------------------------------------------
InsightType = Literal[
    "trend", "cross_doc_validation", "peer_comparison",
    "pattern_detection", "risk", "optimization",
]


class Insight(StrictModel):
    insight_type: InsightType
    severity: Severity
    title: str
    body: str
    evidence: list[str] = Field(default_factory=list)
    affected_documents: list[UUID] = Field(default_factory=list)


class Reflection(StrictModel):
    pattern_id: UUID | None = None
    verdict: Literal["strong", "watch", "weak"]
    reason: str = ""
    metrics: dict[str, float] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Stages 12, 13 — Coverage + Group discovery
# ---------------------------------------------------------------------------
class DocumentGroup(StrictModel):
    group_id: str
    shared_keys: dict[str, str]  # e.g. {"account_number": "0133442501"}
    document_ids: list[UUID]
    coverage: Literal["full", "partial", "orphan"] = "orphan"


# ---------------------------------------------------------------------------
# Stage 14 — Account Briefing
# ---------------------------------------------------------------------------
class MoneyPicture(StrictModel):
    committed: float | None = None
    billed: float | None = None
    paid: float | None = None
    currency: str = "USD"
    shortfall: float | None = None
    overpayment: float | None = None


class TimelineEvent(StrictModel):
    occurred_at: datetime
    description: str
    document_id: UUID | None = None


class ActionItem(StrictModel):
    severity: Severity
    title: str
    detail: str = ""


class AccountBriefing(StrictModel):
    group_id: str
    money: MoneyPicture
    timeline: list[TimelineEvent] = Field(default_factory=list)
    actions: list[ActionItem] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Stages 15, 16 — Narrator + BatchReport
# ---------------------------------------------------------------------------
class GraphDelta(StrictModel):
    nodes_added: int = 0
    edges_added: int = 0
    merges_proposed: int = 0
    isolated_nodes: int = 0
    cross_domain_bridges: int = 0


class BatchReport(StrictModel):
    batch_id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    started_at: datetime
    finished_at: datetime
    documents: list[IngestedDocument] = Field(default_factory=list)
    clusters: dict[UUID, Cluster] = Field(default_factory=dict)
    extractions: dict[UUID, Extraction] = Field(default_factory=dict)
    anomalies: list[Anomaly] = Field(default_factory=list)
    insights: list[Insight] = Field(default_factory=list)
    reflections: list[Reflection] = Field(default_factory=list)
    groups: list[DocumentGroup] = Field(default_factory=list)
    briefings: list[AccountBriefing] = Field(default_factory=list)
    narrator_summary: str = ""
    graph_delta: GraphDelta = Field(default_factory=GraphDelta)
    total_cost_usd: float = 0.0
    progress: list[str] = Field(default_factory=list)
    # Per-stage evaluation results. Each item is a StageEvalResult serialised
    # as a dict (we keep it untyped here to avoid a circular import; the
    # eval module owns the canonical schema).
    stage_evals: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("finished_at")
    @classmethod
    def _finished_after_started(cls, v: datetime, info: Any) -> datetime:
        started = info.data.get("started_at")
        if started and v < started:
            raise ValueError("finished_at must be >= started_at")
        return v


# ---------------------------------------------------------------------------
# Chat (supporting layer)
# ---------------------------------------------------------------------------
class ChatTurn(StrictModel):
    role: Literal["user", "assistant", "system"]
    content: str
    citations: list[UUID] = Field(default_factory=list)


class ChatRequest(StrictModel):
    question: str
    history: list[ChatTurn] = Field(default_factory=list)


class ChatResponse(StrictModel):
    answer: str
    route: Literal["graph", "llm", "hybrid"]
    citations: list[UUID] = Field(default_factory=list)
    elapsed_ms: int = 0


# ---------------------------------------------------------------------------
# Cost tracking
# ---------------------------------------------------------------------------
class LLMCall(StrictModel):
    organ: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    request_id: str | None = None


__all__ = [
    "AccountBriefing",
    "ActionItem",
    "Anomaly",
    "BatchReport",
    "ChatRequest",
    "ChatResponse",
    "ChatTurn",
    "Cluster",
    "CorrectionHint",
    "DocumentGroup",
    "EdgeType",
    "Extraction",
    "FieldDef",
    "FieldExtraction",
    "GraphDelta",
    "IngestedDocument",
    "Insight",
    "InsightType",
    "LLMCall",
    "MemoryHit",
    "MoneyPicture",
    "NodeType",
    "Reflection",
    "Rule",
    "RuleSet",
    "Schema",
    "Severity",
    "TimelineEvent",
    "ValidationResult",
]
