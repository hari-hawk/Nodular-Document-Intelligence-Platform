"""Pricing anomalies — amounts that are statistical outliers.

For each (vendor, field-where-field-is-a-money-field) cluster, compute
the median + MAD (median absolute deviation) and flag values that fall
outside the configured threshold band.

Why MAD instead of mean + N-sigma:
  - The batches in production are SMALL (often <30 docs). With small N
    the sample standard deviation is noisy and easily warped by a single
    outlier — which is exactly what we're trying to detect.
  - MAD is robust to outliers by construction: removing the outlier
    doesn't move the median or MAD much.
  - DD's original implementation used N-sigma which produced false
    positives at small N; we pre-emptively use MAD here.

Threshold ladder (modified z-score using MAD):
  - |z| >= 3.5   → HIGH severity (textbook outlier threshold for MAD)
  - |z| >= 2.5   → MEDIUM
  - |z| < 2.5    → not flagged

The 3.5 / 2.5 thresholds come from Iglewicz & Hoaglin (1993, NIST
recommendation). We use them rather than reinvent.
"""
from __future__ import annotations

import statistics
import uuid
from collections import defaultdict

from mdi.models.schemas import Cluster, Extraction, Insight

# Fields the detector treats as money. Open-vocab is intentional — we
# match by canonical name (Wave 1.x aliases collapse the variants) so a
# new pack with `total` / `monthly_recurring_cost` / `unit_price` works
# without code changes.
_MONEY_FIELDS = frozenset({
    "total", "subtotal", "monthly_recurring_cost", "unit_price",
    "amount", "base_salary", "annual_spend_cap",
})

# A modified z-score scaling constant: 0.6745 is the 75th percentile of
# the standard normal distribution. The full formula is
# `z = 0.6745 * (x - median) / MAD`. We inline it.
_MAD_SCALE = 0.6745


def detect_pricing_anomalies(
    clusters: dict[uuid.UUID, Cluster],
    extractions: dict[uuid.UUID, Extraction],
    *,
    min_cluster_size: int = 4,
    medium_threshold: float = 2.5,
    high_threshold: float = 3.5,
) -> list[Insight]:
    """Return one finding per anomalous (vendor, money-field, document) triple.

    Args:
      clusters: document_id → Cluster
      extractions: document_id → Extraction
      min_cluster_size: skip clusters with fewer than N data points
        (anomaly detection on N=3 is meaningless noise; default 4 is the
        minimum where median/MAD are stable)
      medium_threshold: |modified z| above which severity is MEDIUM
      high_threshold: |modified z| above which severity is HIGH
    """
    # Bucket values by (vendor, field). Skip None / non-numeric.
    by_vendor_field: dict[tuple[str, str], list[tuple[uuid.UUID, float]]] = \
        defaultdict(list)

    for doc_id, ex in extractions.items():
        cluster = clusters.get(doc_id)
        if not cluster:
            continue
        vendor = (cluster.vendor or "").strip().lower()
        if not vendor or vendor == "unknown":
            continue
        for field_name, field in ex.fields.items():
            if field_name not in _MONEY_FIELDS:
                continue
            v = field.value if hasattr(field, "value") else field
            try:
                num = float(v) if v is not None else None
            except (TypeError, ValueError):
                continue
            if num is None:
                continue
            by_vendor_field[(vendor, field_name)].append((doc_id, num))

    findings: list[Insight] = []

    for (vendor, field_name), points in by_vendor_field.items():
        if len(points) < min_cluster_size:
            continue
        values = [p[1] for p in points]
        median = statistics.median(values)
        mad_values = [abs(v - median) for v in values]
        mad = statistics.median(mad_values)
        if mad == 0:
            # All values identical — no anomaly possible.
            continue

        for doc_id, v in points:
            z = _MAD_SCALE * (v - median) / mad
            absz = abs(z)
            if absz < medium_threshold:
                continue

            severity = "HIGH" if absz >= high_threshold else "MEDIUM"
            direction = "above" if z > 0 else "below"
            findings.append(Insight(
                insight_type="risk",
                severity=severity,  # type: ignore[arg-type]
                title=(
                    f"{vendor}: {field_name}={v:.2f} is {absz:.1f}σ {direction} "
                    f"the median ({median:.2f})"
                ),
                body=(
                    f"Across {len(points)} {vendor} documents in this batch, "
                    f"{field_name} has median {median:.2f} and MAD {mad:.2f}. "
                    f"This document's value ({v:.2f}) is a modified z-score "
                    f"of {z:+.1f} — worth a closer look."
                ),
                evidence=[],
                affected_documents=[doc_id],
            ))

    return findings
