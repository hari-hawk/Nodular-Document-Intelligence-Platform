"""The 19-stage pipeline. Single entry point: `run_batch_async`.

Stages (per synthesis Section 16):

  Phase 1 — per-doc                    Phase 2 — batch
   0  page-limit gate                  10 comparative analysis (Insight Cortex)
   1  ingest                           11 reflection (Inner Voice)
   2  classify (Eyes)                  12 group discovery
   3  memory check (Hippocampus)       13 coverage classification
   4  schema discovery (Pattern Cortex)
   5  rule invention (Conscience)      Phase 3 — report
   6  correction lookup (Hippocampus)  14 account briefings
   7  extract (Hands)                  15 narrator
   8  validate (Conscience)            16 BatchReport assembly
   9  memory write (Hippocampus)
                                       Phase 4 — graph
                                       17 graph build
                                       18 graph insights
                                       19 cross-doc validation

Concurrency: organs run with a shared `Semaphore(settings.organ_concurrency)`
so the LLM Gateway never sees more than N concurrent calls.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

from mdi.brain import (
    account_briefing,
    chat,  # noqa: F401  — re-exports for orchestrator users
    conscience,
    coverage,
    eyes,
    graph_builder,
    hands,
    inner_voice,
    insight_cortex,
    narrator,
    pattern_cortex,
)
from mdi.brain.hippocampus import Hippocampus, baseline_rules_from_schema
from mdi.brain.knowledge_graph import KnowledgeGraph
from mdi.kernel import ingest as ingest_mod
from mdi.kernel.auth import tenant_session
from mdi.kernel.llm_gateway import GatewayLike, get_gateway
from mdi.kernel.observability import get_logger
from mdi.kernel.settings import get_settings
from mdi.models.db import (
    Anomaly as AnomalyRow,
)
from mdi.models.db import (
    AuditEvent,
    Batch,
)
from mdi.models.db import (
    Document as DocumentRow,
)
from mdi.models.db import (
    Extraction as ExtractionRow,
)
from mdi.models.schemas import (
    Anomaly,
    BatchReport,
    Cluster,
    Extraction,
    GraphDelta,
    IngestedDocument,
    MemoryHit,
    Reflection,
    RuleSet,
    Schema,
)
from mdi.orchestrator.progress import ProgressBus

logger = get_logger(__name__)


class PageLimitExceeded(RuntimeError):
    """Raised when a document exceeds the hard page cap."""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
async def run_batch_async(
    *,
    tenant_id: str | uuid.UUID,
    payloads: list[dict[str, Any]],
    gateway: GatewayLike | None = None,
    hippocampus: Hippocampus | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """Process a batch and return its BatchReport as JSON.

    `payloads` items: {"filename": str, "content": bytes-or-base64, "force_vision": bool?}.
    Set `persist=False` for tests that don't want DB writes (still requires a valid
    tenant_id format but skips all SQL).
    """
    s = get_settings()
    semaphore = asyncio.Semaphore(s.organ_concurrency)
    bus = ProgressBus()
    started = datetime.now(UTC)
    tid = uuid.UUID(str(tenant_id))
    gw = gateway or get_gateway()
    # `Hippocampus()` with no arg defers to settings.use_real_embeddings
    # (stub by default, bge-m3 in production). Callers can override by
    # passing an explicit Hippocampus instance.
    hippo = hippocampus or Hippocampus()

    documents: list[IngestedDocument] = []
    clusters: dict[uuid.UUID, Cluster] = {}
    extractions: dict[uuid.UUID, Extraction] = {}
    anomalies: list[Anomaly] = []
    # Per-stage EvalLayer results - populated as each stage completes.
    stage_evals: list[dict[str, Any]] = []
    # Wave 2.1 — multi-pattern recognition. The full ranked list of
    # pattern candidates per document. Item shape:
    # {document_id, pattern_id, similarity, rank}.
    pattern_matches: list[dict[str, Any]] = []

    # Lazy import to avoid circular dependency.
    from mdi.eval.stage_eval import make_eval as _make_eval

    # Per-tenant EvalLayer thresholds (Option A). Read once per batch from
    # tenants.config JSONB; missing keys fall back to the per-stage default.
    tenant_thresholds: dict[str, float] = {}
    if persist:
        try:
            from sqlalchemy import text as _sql_text
            async with tenant_session(tid) as _db:
                _row = (await _db.execute(
                    _sql_text("SELECT config FROM tenants WHERE id = :tid"),
                    {"tid": str(tid)},
                )).first()
                if _row and _row.config:
                    tenant_thresholds = (_row.config or {}).get("eval_thresholds", {}) or {}
        except Exception:
            tenant_thresholds = {}

    assess_classify = _make_eval("classify",         tenant_thresholds=tenant_thresholds)
    assess_schema   = _make_eval("schema_discovery", tenant_thresholds=tenant_thresholds)
    assess_extract  = _make_eval("extract",          tenant_thresholds=tenant_thresholds)
    assess_validate = _make_eval("validate",         tenant_thresholds=tenant_thresholds)
    assess_insights = _make_eval("insights",         tenant_thresholds=tenant_thresholds)
    assess_graph    = _make_eval("graph",            tenant_thresholds=tenant_thresholds)

    # ------------------------------------------------------------------
    # Phase 1 — per-document
    # ------------------------------------------------------------------
    async def per_document(payload: dict[str, Any]) -> None:
        async with semaphore:
            # Stage 1 — ingest
            content = payload["content"]
            if isinstance(content, str):
                import base64
                content = base64.b64decode(content)
            doc = ingest_mod.ingest(payload["filename"], content)
            # Stage 0 — page-limit gate
            if doc.page_count > s.page_limit_hard:
                raise PageLimitExceeded(
                    f"{doc.filename}: {doc.page_count} pages exceeds hard cap {s.page_limit_hard}"
                )
            await bus.publish(1, "ingest", doc.filename, page_count=doc.page_count)

            # Stage 2 — classify
            cluster = await eyes.classify(doc, gateway=gw)
            await bus.publish(2, "classify", f"{cluster.industry}|{cluster.vendor}|{cluster.doc_type}",
                              confidence=cluster.confidence)
            documents.append(doc)
            clusters[doc.document_id] = cluster
            # EvalLayer: classification quality
            stage_evals.append(assess_classify.evaluate(doc, cluster).model_dump(mode="json"))

            schema: Schema
            ruleset: RuleSet
            invented: RuleSet
            corrections = []
            pattern_id: uuid.UUID | None = None
            memory_hit: MemoryHit | None = None

            if persist:
                async with tenant_session(tid) as db:
                    # Stage 3 — memory check. Multi-pattern retrieval lands
                    # the full ranked candidate set so the Patterns page can
                    # show "this document also resembled these patterns".
                    # The pipeline still acts on the top hit (if it clears
                    # the 0.82 SIMILARITY_THRESHOLD) — but downstream consumers
                    # see the candidates the brain considered.
                    multi_matches = await hippo.lookup_patterns_multi(
                        db, tid, cluster, top_k=5, min_similarity=0.50,
                    )
                    for rank, mh in enumerate(multi_matches):
                        pattern_matches.append({
                            "document_id": str(doc.document_id),
                            "pattern_id": str(mh.pattern_id),
                            "similarity": mh.similarity,
                            "rank": rank,
                        })
                    memory_hit = await hippo.lookup_pattern(db, tid, cluster)
                    if memory_hit:
                        await bus.publish(3, "memory.hit",
                                          f"similarity={memory_hit.similarity:.2f}")
                        schema = memory_hit.schema_
                        ruleset = memory_hit.rules
                        pattern_id = memory_hit.pattern_id
                        invented = RuleSet(rules=[])
                    else:
                        await bus.publish(3, "memory.miss", "no similar pattern")
                        # Stage 4 — schema discovery
                        schema = await pattern_cortex.discover(doc, cluster, gateway=gw)
                        await bus.publish(4, "schema.discovered", f"{len(schema.fields)} fields")
                        # Stage 5 — rule invention
                        invented = await conscience.invent(schema, None, cluster, gateway=gw)
                        await bus.publish(5, "rules.invented", f"{len(invented.rules)} (gated)")
                        ruleset = baseline_rules_from_schema(schema)
                        ruleset = RuleSet(rules=ruleset.rules + invented.rules)

                    # Stage 6 — correction lookup
                    corrections = await hippo.get_corrections(db, tid, cluster)
                    await bus.publish(6, "corrections", f"{len(corrections)}")
            else:
                schema = await pattern_cortex.discover(doc, cluster, gateway=gw)
                await bus.publish(4, "schema.discovered", f"{len(schema.fields)} fields (transient)")
                invented = await conscience.invent(schema, None, cluster, gateway=gw)
                ruleset = baseline_rules_from_schema(schema)
                ruleset = RuleSet(rules=ruleset.rules + invented.rules)

            # EvalLayer: schema discovery quality
            stage_evals.append(assess_schema.evaluate(doc, schema).model_dump(mode="json"))

            # Stage 7 - extract
            ex = await hands.extract(doc, cluster, schema, corrections,
                                     pattern_id=pattern_id, gateway=gw)
            # Normalise field names at the extraction boundary so every
            # downstream consumer (DB, API, exports, UI) sees one canonical
            # name per concept. Schema (Pattern Cortex output) keeps raw
            # names — Patterns tab is meant to show what the brain saw.
            from mdi.brain._canonical_fields import normalize_extraction
            ex = normalize_extraction(ex)
            await bus.publish(7, "extracted", f"{len(ex.fields)} fields", cost_usd=ex.cost_usd)
            # EvalLayer: extraction quality
            stage_evals.append(assess_extract.evaluate(schema, ex).model_dump(mode="json"))

            # Stage 8 - validate
            vr = conscience.validate(ex, ruleset)
            anomalies.extend(vr.anomalies)
            await bus.publish(8, "validated", f"{len(vr.anomalies)} anomalies")
            # EvalLayer: validation quality
            stage_evals.append(assess_validate.evaluate(ruleset, ex, vr).model_dump(mode="json"))

            extractions[doc.document_id] = ex

            if persist:
                async with tenant_session(tid) as db:
                    # Persist document
                    db.add(
                        DocumentRow(
                            id=doc.document_id,
                            tenant_id=tid,
                            filename=doc.filename,
                            mime_type=doc.mime_type,
                            page_count=doc.page_count,
                            bytes=doc.bytes,
                            sha256=doc.sha256,
                            cluster=cluster.model_dump(),
                            layout=cluster.layout,
                        )
                    )
                    db.add(
                        ExtractionRow(
                            tenant_id=tid,
                            document_id=doc.document_id,
                            fields={k: v.model_dump() for k, v in ex.fields.items()},
                            field_confidences={k: v.confidence for k, v in ex.fields.items()},
                            field_provenance={k: v.source_text for k, v in ex.fields.items()},
                            extraction_cost_usd=ex.cost_usd,
                        )
                    )
                    # Materialise parents before children — anomalies and the
                    # audit row reference document_id, and SQLAlchemy's bulk
                    # insert path doesn't reorder across tables.
                    await db.flush()
                    for a in vr.anomalies:
                        db.add(
                            AnomalyRow(
                                tenant_id=tid,
                                document_id=doc.document_id,
                                rule_id=a.rule_id,
                                severity=a.severity,
                                field_path=a.field_path,
                                message=a.message,
                                context=a.context,
                                invented=a.invented,
                            )
                        )
                    # Auto-pack proposal (Wave 1.2 of the DD uplift).
                    # When the pipeline ran in open-vocab / base-pack mode AND
                    # the extraction surfaced a real vendor, queue an auto-pack
                    # proposal so analysts can one-click-promote the vendor
                    # into its own pack. Has zero influence on the current
                    # extraction — proposals start in `pending` and don't
                    # affect routing until promoted.
                    try:
                        from mdi.kernel.auto_pack_registry import propose_pack
                        vendor_field = ex.fields.get("vendor")
                        used_base_pack = (
                            schema.pack_slug in (None, "business_documents_base")
                        )
                        if vendor_field and used_base_pack:
                            v_value = vendor_field.value
                            v_name = (
                                v_value.get("name") if isinstance(v_value, dict)
                                else v_value
                            )
                            if isinstance(v_name, str) and v_name.strip():
                                await propose_pack(
                                    db,
                                    tenant_id=tid,
                                    vendor_name=v_name,
                                    doc_type_hint=cluster.doc_type,
                                    first_seen_doc_id=doc.document_id,
                                    sample_extraction={
                                        k: (v.value if hasattr(v, "value") else v)
                                        for k, v in list(ex.fields.items())[:8]
                                    },
                                )
                    except Exception as _e:
                        # Never let an auto-pack DB hiccup break extraction;
                        # this is a side-channel feature.
                        logger.warning("auto_pack.hook_failed", error=str(_e))

                    # Stage 9 — memory write
                    pid = await hippo.write_pattern(
                        db, tid, cluster, schema, ruleset, pattern_id=pattern_id
                    )
                    db.add(
                        AuditEvent(
                            tenant_id=tid,
                            actor="orchestrator",
                            action="document.processed",
                            object_type="document",
                            object_id=str(doc.document_id),
                            payload={
                                "filename": doc.filename,
                                "memory_hit": memory_hit is not None,
                                "anomaly_count": len(vr.anomalies),
                                "cost_usd": ex.cost_usd,
                                "pattern_id": str(pid),
                            },
                        )
                    )
                    await db.commit()
                    await bus.publish(9, "memory.written", f"pattern_id={pid}")

                # RAG indexing runs in its OWN tenant_session so the
                # app.tenant_id GUC is freshly set on whatever connection
                # we acquire. Without this, asyncpg pool rotation after the
                # commit above can yield a connection that lost the GUC, and
                # the RLS policy then rejects the inserts with
                # InsufficientPrivilegeError.
                try:
                    from mdi.brain.rag import RAGIndex
                    rag = RAGIndex(use_real_embeddings=False)
                    async with tenant_session(tid) as rag_db:
                        n_chunks = await rag.index_document(
                            rag_db, tenant_id=tid,
                            document_id=doc.document_id,
                            document_text=doc.text or "",
                        )
                        await rag_db.commit()
                    await bus.publish(9, "rag.indexed", f"{n_chunks} chunks")
                except Exception as _e:
                    # Surface the message — silent ProgrammingError used to
                    # hide bind-parameter and RLS issues completely.
                    await bus.publish(9, "rag.skipped",
                                      f"{type(_e).__name__}: {str(_e)[:160]}")

    await asyncio.gather(*(per_document(p) for p in payloads))

    # ------------------------------------------------------------------
    # Phase 2 — batch
    # ------------------------------------------------------------------
    insights = await insight_cortex.analyse(list(extractions.values()), anomalies, gateway=gw)
    await bus.publish(10, "insights", f"{len(insights)}")
    # EvalLayer: insight quality
    stage_evals.append(assess_insights.evaluate(list(extractions.values()), insights).model_dump(mode="json"))
    reflections: list[Reflection] = [
        inner_voice.reflect(
            pattern_id=None,
            extractions=list(extractions.values()),
            anomalies=anomalies,
        )
    ]
    await bus.publish(11, "reflection", reflections[0].verdict)

    extractions_by_str = {str(k): v for k, v in extractions.items()}
    clusters_by_str = {str(k): v for k, v in clusters.items()}

    groups = coverage.discover_groups(extractions_by_str)
    await bus.publish(12, "groups", f"{len(groups)} discovered")
    groups = coverage.classify_groups(groups, extractions_by_str, clusters_by_str)
    await bus.publish(13, "coverage", "classified")

    # ------------------------------------------------------------------
    # Phase 3 — report
    # ------------------------------------------------------------------
    briefings = account_briefing.brief_all(groups, extractions_by_str, clusters_by_str)
    await bus.publish(14, "briefings", f"{len(briefings)}")

    summary = await narrator.narrate(
        n_documents=len(documents),
        insights=insights,
        anomalies=anomalies,
        briefings=briefings,
        gateway=gw,
    )
    await bus.publish(15, "narrator", summary[:120])

    # ------------------------------------------------------------------
    # Phase 4 — knowledge graph + cross-doc validation
    # ------------------------------------------------------------------
    graph_delta = GraphDelta()
    if persist:
        async with tenant_session(tid) as db:
            kg = KnowledgeGraph(db)
            partial_report = BatchReport(
                tenant_id=tid,
                started_at=started,
                finished_at=datetime.now(UTC),
                documents=documents,
                clusters=clusters,
                extractions=extractions,
            )
            graph_delta = await graph_builder.build_graph(
                kg=kg, tenant_id=tid, report=partial_report
            )
            await db.commit()
        await bus.publish(17, "graph", f"+{graph_delta.nodes_added} nodes, +{graph_delta.edges_added} edges")
        # EvalLayer: graph quality
        stage_evals.append(assess_graph.evaluate(
            n_documents=len(documents),
            nodes_added=graph_delta.nodes_added,
            edges_added=graph_delta.edges_added,
            isolated=graph_delta.isolated_nodes,
        ).model_dump(mode="json"))

    finished = datetime.now(UTC)
    await bus.publish(16, "report", "assembled")

    # Total cost = every LLM call routed through the gateway during this
    # batch (Eyes + Pattern Cortex + Hands + Conscience.invent + Narrator +
    # any Chat call). Falls back to the Hands-only sum for gateways that
    # don't expose a cost tracker (e.g. tests with stub gateways).
    total_cost = sum(e.cost_usd for e in extractions.values())
    tracker = getattr(gw, "cost_tracker", None)
    if tracker is not None and hasattr(tracker, "events"):
        total_cost = sum(c.cost_usd for c in tracker.events)

    report = BatchReport(
        tenant_id=tid,
        started_at=started,
        finished_at=finished,
        documents=documents,
        clusters=clusters,
        extractions=extractions,
        anomalies=anomalies,
        insights=insights,
        reflections=reflections,
        groups=groups,
        briefings=briefings,
        narrator_summary=summary,
        graph_delta=graph_delta,
        total_cost_usd=total_cost,
        progress=[f"[{e.stage:02d}] {e.name}: {e.detail}" for e in bus.history],
        stage_evals=stage_evals,
        pattern_matches=pattern_matches,
    )

    if persist:
        async with tenant_session(tid) as db:
            db.add(
                Batch(
                    tenant_id=tid,
                    status="finished",
                    total_documents=len(documents),
                    started_at=started,
                    finished_at=finished,
                    cost_usd=report.total_cost_usd,
                    report=report.model_dump(mode="json"),
                )
            )
            await db.commit()

    await bus.close()
    return report.model_dump(mode="json")
