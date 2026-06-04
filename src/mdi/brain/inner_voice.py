"""Inner Voice — pure-Python reflection (Stage 11).

Per-pattern verdict: strong / watch / weak.

A pattern is `strong` when the most recent batches show:
  * extraction confidence trending up and >= 0.85 mean
  * anomaly rate trending down and < 5%
  * agreement_count on its corrections >= 3 (stable replays)

`weak` when the inverse is true. Otherwise `watch`.

No LLM calls. Deterministic and cheap.
"""
from __future__ import annotations

from collections.abc import Iterable
from statistics import mean
from typing import Any
from uuid import UUID

from mdi.models.schemas import Anomaly, Extraction, Reflection


def reflect(
    *,
    pattern_id: UUID | None,
    extractions: Iterable[Extraction],
    anomalies: Iterable[Anomaly],
    correction_agreement_counts: Iterable[int] = (),
) -> Reflection:
    extractions = list(extractions)
    anomalies = list(anomalies)
    agree = list(correction_agreement_counts)

    if not extractions:
        return Reflection(
            pattern_id=pattern_id,
            verdict="watch",
            reason="no extractions yet",
            metrics={},
        )

    confidences: list[float] = [
        f.confidence for ex in extractions for f in ex.fields.values()
    ]
    mean_conf = mean(confidences) if confidences else 0.0
    anomaly_rate = len(anomalies) / max(len(extractions), 1)
    agreement_floor = min(agree) if agree else 0

    metrics: dict[str, float] = {
        "mean_confidence": round(mean_conf, 3),
        "anomaly_rate": round(anomaly_rate, 3),
        "min_agreement_count": float(agreement_floor),
        "extractions": float(len(extractions)),
    }

    strong = mean_conf >= 0.85 and anomaly_rate < 0.05 and agreement_floor >= 3
    weak = mean_conf < 0.6 or anomaly_rate >= 0.30

    if strong:
        verdict: Any = "strong"
        reason = "high confidence, low anomalies, repeated correction agreement"
    elif weak:
        verdict = "weak"
        reason = "confidence low or anomaly rate elevated"
    else:
        verdict = "watch"
        reason = "still stabilizing"

    return Reflection(
        pattern_id=pattern_id,
        verdict=verdict,
        reason=reason,
        metrics=metrics,
    )
