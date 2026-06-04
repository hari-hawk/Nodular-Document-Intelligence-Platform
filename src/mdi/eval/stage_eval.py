"""Per-stage evaluation layer.

Every cognitive organ produces an output. Today we trust those outputs
blindly. EvalLayer wraps each organ with a deterministic post-check:

  organ.run() -> EvalLayer.evaluate(input, output) -> StageEvalResult

A StageEvalResult carries:
  - score      0..1 (1 = perfect, 0 = catastrophic)
  - passed     bool (score >= threshold)
  - checks     list of Check(name, passed, detail)
  - severity   HIGH/MEDIUM/LOW/INFO
  - attributes per-stage diagnostic numbers

Adding a new EvalLayer:
  1. Subclass StageEval
  2. Implement an `evaluate` method returning StageEvalResult
  3. Register it in STAGE_EVALS
  4. The orchestrator wires it automatically
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from mdi.models.schemas import (
    Cluster,
    Extraction,
    IngestedDocument,
    Insight,
    RuleSet,
    Schema,
    StrictModel,
    ValidationResult,
)

Severity = Literal["HIGH", "MEDIUM", "LOW", "INFO"]


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------
class Check(StrictModel):
    name: str
    passed: bool
    detail: str = ""


class StageEvalResult(StrictModel):
    stage_name: str
    organ: str
    document_id: UUID | None = None
    score: float
    passed: bool
    severity: Severity = "MEDIUM"
    checks: list[Check]
    attributes: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------
@dataclass
class StageEval:
    """Base for per-stage evaluators. Subclasses implement an `evaluate` method."""

    stage_name: str
    organ: str
    threshold: float = 0.6
    severity_on_fail: Severity = "MEDIUM"

    def _result(
        self,
        *,
        checks: list[Check],
        document_id: UUID | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> StageEvalResult:
        passed_count = sum(1 for c in checks if c.passed)
        score = (passed_count / max(len(checks), 1)) if checks else 1.0
        passed = score >= self.threshold
        return StageEvalResult(
            stage_name=self.stage_name,
            organ=self.organ,
            document_id=document_id,
            score=round(score, 3),
            passed=passed,
            severity=self.severity_on_fail if not passed else "INFO",
            checks=checks,
            attributes=attributes or {},
        )


# ---------------------------------------------------------------------------
# Stage 2 - Eyes (classification)
# ---------------------------------------------------------------------------
class ClassifyEval(StageEval):
    def __init__(self) -> None:
        super().__init__(stage_name="02_classify", organ="eyes", threshold=0.6,
                         severity_on_fail="MEDIUM")

    def evaluate(self, doc: IngestedDocument, cluster: Cluster) -> StageEvalResult:
        checks = [
            Check(name="industry_present",
                  passed=bool(cluster.industry) and cluster.industry != "unknown",
                  detail=f"industry={cluster.industry!r}"),
            Check(name="vendor_present",
                  passed=bool(cluster.vendor) and cluster.vendor.lower() != "unknown",
                  detail=f"vendor={cluster.vendor!r}"),
            Check(name="doc_type_present",
                  passed=bool(cluster.doc_type) and cluster.doc_type != "unknown",
                  detail=f"doc_type={cluster.doc_type!r}"),
            Check(name="confidence_above_threshold",
                  passed=cluster.confidence >= 0.5,
                  detail=f"confidence={cluster.confidence:.2f}"),
            Check(name="layout_valid",
                  passed=cluster.layout in {"tabular", "form", "free_text", "scanned", "mixed"},
                  detail=f"layout={cluster.layout!r}"),
        ]
        return self._result(
            checks=checks,
            document_id=doc.document_id,
            attributes={"confidence": cluster.confidence,
                        "industry": cluster.industry,
                        "doc_type": cluster.doc_type},
        )


# ---------------------------------------------------------------------------
# Stage 4 - Pattern Cortex (schema discovery)
# ---------------------------------------------------------------------------
class SchemaEval(StageEval):
    def __init__(self) -> None:
        super().__init__(stage_name="04_schema_discovery", organ="pattern_cortex",
                         threshold=0.6, severity_on_fail="MEDIUM")

    def evaluate(self, doc: IngestedDocument, schema: Schema) -> StageEvalResult:
        n_fields = len(schema.fields)
        n_required = sum(1 for f in schema.fields if f.required)
        n_typed = sum(1 for f in schema.fields if f.type in
                      {"string", "number", "date", "currency", "boolean", "list", "object"})
        checks = [
            Check(name="has_minimum_fields", passed=n_fields >= 3,
                  detail=f"{n_fields} fields (>= 3 expected)"),
            Check(name="all_fields_typed", passed=n_typed == n_fields,
                  detail=f"{n_typed}/{n_fields} fields have known types"),
            Check(name="has_at_least_one_required", passed=n_required >= 1,
                  detail=f"{n_required} required fields"),
            Check(name="discovery_source_set",
                  passed=schema.discovered_from in {"memory", "discovery", "pack"},
                  detail=f"discovered_from={schema.discovered_from}"),
        ]
        return self._result(
            checks=checks,
            document_id=doc.document_id,
            attributes={"n_fields": n_fields, "n_required": n_required,
                        "discovered_from": schema.discovered_from},
        )


# ---------------------------------------------------------------------------
# Stage 7 - Hands (extraction)
# ---------------------------------------------------------------------------
class ExtractEval(StageEval):
    def __init__(self) -> None:
        super().__init__(stage_name="07_extract", organ="hands", threshold=0.6,
                         severity_on_fail="HIGH")

    def evaluate(self, schema: Schema, extraction: Extraction) -> StageEvalResult:
        required_names = {f.name for f in schema.fields if f.required}
        populated = {k for k, v in extraction.fields.items() if v.value is not None}
        mean_conf = (sum(v.confidence for v in extraction.fields.values()) /
                     max(len(extraction.fields), 1))
        provenance_pct = (sum(1 for v in extraction.fields.values() if v.source_text) /
                          max(len(extraction.fields), 1))
        required_populated_pct = (
            len(required_names & populated) / max(len(required_names), 1)
            if required_names else 1.0
        )
        checks = [
            Check(name="fields_returned", passed=len(extraction.fields) > 0,
                  detail=f"{len(extraction.fields)} fields extracted"),
            Check(name="required_fields_populated",
                  passed=required_populated_pct >= 0.8,
                  detail=f"{int(required_populated_pct*100)}% of required fields populated"),
            Check(name="mean_confidence_acceptable", passed=mean_conf >= 0.6,
                  detail=f"mean_confidence={mean_conf:.2f}"),
            Check(name="provenance_rate_reasonable", passed=provenance_pct >= 0.3,
                  detail=f"{int(provenance_pct*100)}% of fields have source_text"),
            Check(name="cost_reasonable", passed=extraction.cost_usd < 0.10,
                  detail=f"cost=${extraction.cost_usd:.5f}"),
        ]
        return self._result(
            checks=checks,
            document_id=extraction.document_id,
            attributes={"n_extracted": len(extraction.fields),
                        "n_populated": len(populated),
                        "mean_confidence": round(mean_conf, 3),
                        "provenance_pct": round(provenance_pct, 3),
                        "cost_usd": extraction.cost_usd},
        )


# ---------------------------------------------------------------------------
# Stage 8 - Conscience (validation)
# ---------------------------------------------------------------------------
class ValidateEval(StageEval):
    def __init__(self) -> None:
        super().__init__(stage_name="08_validate", organ="conscience", threshold=0.7,
                         severity_on_fail="MEDIUM")

    def evaluate(self, ruleset: RuleSet, extraction: Extraction,
                 vr: ValidationResult) -> StageEvalResult:
        n_rules_run = sum(1 for r in ruleset.rules if r.enabled)
        n_anomalies = len(vr.anomalies)
        n_rule_errors = sum(1 for a in vr.anomalies if "rule errored" in a.message)
        n_high = sum(1 for a in vr.anomalies if a.severity == "HIGH")
        checks = [
            Check(name="rules_actually_ran", passed=n_rules_run > 0,
                  detail=f"{n_rules_run} rules enabled"),
            Check(name="no_rule_execution_errors", passed=n_rule_errors == 0,
                  detail=f"{n_rule_errors} rule(s) errored at runtime"),
            Check(name="anomaly_rate_reasonable",
                  passed=(n_anomalies / max(n_rules_run, 1)) < 0.5,
                  detail=f"{n_anomalies}/{n_rules_run} rules flagged anomalies"),
            Check(name="no_invented_rules_unreviewed",
                  passed=not any(a.invented and a.severity == "HIGH" for a in vr.anomalies),
                  detail="invented HIGH-severity rules need analyst approval"),
        ]
        return self._result(
            checks=checks,
            document_id=extraction.document_id,
            attributes={"n_rules": n_rules_run, "n_anomalies": n_anomalies,
                        "n_high_severity": n_high, "n_rule_errors": n_rule_errors},
        )


# ---------------------------------------------------------------------------
# Stage 10 - Insight Cortex
# ---------------------------------------------------------------------------
class InsightEval(StageEval):
    def __init__(self) -> None:
        super().__init__(stage_name="10_insights", organ="insight_cortex",
                         threshold=0.5, severity_on_fail="LOW")

    def evaluate(self, extractions: list[Extraction],
                 insights: list[Insight]) -> StageEvalResult:
        checks = [
            Check(name="insights_well_formed",
                  passed=all(bool(i.title) and bool(i.body) for i in insights),
                  detail=f"{len(insights)} insights, all have title+body"),
            Check(name="severity_distribution_sane",
                  passed=all(i.severity in {"HIGH", "MEDIUM", "LOW", "INFO"}
                             for i in insights),
                  detail="all insights use the defined severity vocabulary"),
            Check(name="affected_documents_referenced",
                  passed=all(i.affected_documents for i in insights) if insights else True,
                  detail="each insight references at least one document"),
        ]
        return self._result(
            checks=checks,
            attributes={"n_insights": len(insights),
                        "n_high": sum(1 for i in insights if i.severity == "HIGH"),
                        "n_documents": len(extractions)},
        )


# ---------------------------------------------------------------------------
# Stage 17 - Graph Builder
# ---------------------------------------------------------------------------
class GraphEval(StageEval):
    def __init__(self) -> None:
        super().__init__(stage_name="17_graph", organ="graph_builder", threshold=0.5,
                         severity_on_fail="LOW")

    def evaluate(self, n_documents: int, nodes_added: int, edges_added: int,
                 isolated: int) -> StageEvalResult:
        checks = [
            Check(name="nodes_added_for_nonempty_batch",
                  passed=(n_documents == 0) or (nodes_added > 0),
                  detail=f"{nodes_added} nodes added for {n_documents} documents"),
            Check(name="reasonable_node_to_doc_ratio",
                  passed=(n_documents == 0) or
                         (1 <= nodes_added / max(n_documents, 1) <= 10),
                  detail=f"{nodes_added / max(n_documents, 1):.1f} nodes per doc"),
            Check(name="not_all_nodes_isolated",
                  passed=nodes_added == 0 or isolated / max(nodes_added, 1) < 0.7,
                  detail=f"{isolated}/{nodes_added} isolated nodes"),
        ]
        return self._result(
            checks=checks,
            attributes={"n_documents": n_documents, "nodes_added": nodes_added,
                        "edges_added": edges_added, "isolated": isolated},
        )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
STAGE_EVALS: dict[str, type[StageEval]] = {
    "classify": ClassifyEval,
    "schema_discovery": SchemaEval,
    "extract": ExtractEval,
    "validate": ValidateEval,
    "insights": InsightEval,
    "graph": GraphEval,
}


def make_eval(stage_key: str, *, tenant_thresholds: dict[str, float] | None = None) -> StageEval:
    """Factory used by the orchestrator.

    `tenant_thresholds` is read from `tenants.config["eval_thresholds"]` and
    overrides the hardcoded default for this stage. Missing entries fall
    back to the per-class default. Out-of-range values are clamped to [0, 1].
    """
    cls = STAGE_EVALS.get(stage_key)
    if cls is None:
        raise ValueError(f"no eval registered for stage_key={stage_key!r}")
    inst = cls()
    if tenant_thresholds:
        override = tenant_thresholds.get(stage_key)
        if override is not None:
            inst.threshold = max(0.0, min(1.0, float(override)))
    return inst
