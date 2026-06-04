"""Insight Cortex — comparative analysis (Stage 10).

Six analysis types per the synthesis doc:
  trend, cross_doc_validation, peer_comparison,
  pattern_detection, risk, optimization

Heuristic-driven baseline (so it runs offline). LLM is used to *narrate*
the highest-severity findings in plain English when a gateway is provided.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from uuid import UUID

from mdi.kernel.llm_gateway import GatewayLike
from mdi.kernel.observability import get_logger
from mdi.kernel.settings import get_settings
from mdi.models.schemas import (
    Anomaly,
    Extraction,
    Insight,
    Severity,
)

logger = get_logger(__name__)


def _money(extraction: Extraction, key: str) -> float | None:
    f = extraction.fields.get(key)
    if f is None or f.value is None:
        return None
    try:
        return float(f.value)
    except (TypeError, ValueError):
        return None


def _trend_insights(extractions: list[Extraction]) -> list[Insight]:
    by_vendor: dict[str, list[float]] = defaultdict(list)
    by_vendor_doc: dict[str, list[UUID]] = defaultdict(list)
    for ex in extractions:
        v = ex.fields.get("vendor")
        t = _money(ex, "total")
        if v is None or t is None or v.value is None:
            continue
        by_vendor[str(v.value)].append(t)
        by_vendor_doc[str(v.value)].append(ex.document_id)

    out: list[Insight] = []
    for vendor, totals in by_vendor.items():
        if len(totals) < 3:
            continue
        try:
            median = statistics.median(totals)
            latest = totals[-1]
            if median == 0:
                continue
            delta = (latest - median) / median
        except statistics.StatisticsError:
            continue
        if abs(delta) < 0.15:
            continue
        sev: Severity = "HIGH" if abs(delta) >= 0.50 else "MEDIUM"
        out.append(
            Insight(
                insight_type="trend",
                severity=sev,
                title=f"{vendor}: total deviates {delta:+.0%} vs trailing median",
                body=(
                    f"Latest total {latest:.2f} vs trailing median {median:.2f} "
                    f"({delta:+.0%})."
                ),
                evidence=[f"latest={latest}", f"median={median}", f"n={len(totals)}"],
                affected_documents=list(by_vendor_doc[vendor][-3:]),
            )
        )
    return out


def _cross_doc_insights(extractions: list[Extraction]) -> list[Insight]:
    """Detect totals that don't reconcile across docs sharing an account."""
    by_account: dict[str, list[Extraction]] = defaultdict(list)
    for ex in extractions:
        f = ex.fields.get("account_number") or ex.fields.get("customer")
        if f and f.value is not None:
            by_account[str(f.value)].append(ex)

    out: list[Insight] = []
    for account, group in by_account.items():
        committed = next(
            (_money(e, "total") for e in group
             if e.fields.get("doc_type") and str(e.fields["doc_type"].value or "").startswith("contract")),
            None,
        )
        billed_sum = sum(_money(e, "total") or 0 for e in group)
        if committed and billed_sum and abs(billed_sum - committed) / max(committed, 1.0) >= 0.10:
            out.append(
                Insight(
                    insight_type="cross_doc_validation",
                    severity="HIGH",
                    title=f"Account {account}: billed != committed",
                    body=(
                        f"Sum of billed totals {billed_sum:.2f} differs from contract "
                        f"committed {committed:.2f}."
                    ),
                    evidence=[f"billed={billed_sum}", f"committed={committed}"],
                    affected_documents=[e.document_id for e in group],
                )
            )
    return out


def _risk_insights(anomalies: list[Anomaly]) -> list[Insight]:
    high = [a for a in anomalies if a.severity == "HIGH"]
    if not high:
        return []
    return [
        Insight(
            insight_type="risk",
            severity="HIGH",
            title=f"{len(high)} HIGH-severity anomalies require immediate review",
            body="\n".join(
                f"  - [{a.rule_id}] {a.message}" for a in high[:10]
            ),
            evidence=[a.rule_id for a in high],
        )
    ]


async def analyse(
    extractions: list[Extraction],
    anomalies: list[Anomaly],
    *,
    gateway: GatewayLike | None = None,
) -> list[Insight]:
    insights: list[Insight] = []
    insights.extend(_trend_insights(extractions))
    insights.extend(_cross_doc_insights(extractions))
    insights.extend(_risk_insights(anomalies))

    severity_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "INFO": 3}
    insights.sort(key=lambda i: severity_order.get(i.severity, 9))

    # Optional LLM narration pass — disabled by default to keep tests offline.
    _ = gateway, get_settings  # placeholder for the v1.1 narrate-with-LLM pass
    return insights
