"""Deterministic pattern detectors — Wave 2.2 of the DD uplift.

Pure-function findings over a batch of Extractions/Clusters/Anomalies.
Complement (don't replace) the LLM-based Insight Cortex: fast, free,
deterministic, and reliable for the obvious patterns that don't need a
language model's nuance.

Three generic detectors ship in this package — three more from DD's
catalogue (`multi_carrier_same_account`, `m2m_needing_contracts`) are
telecom-specific and intentionally NOT ported. They'd belong in a
future `packs/telecom/detectors/` package as pack-scoped extensions.

Findings use the existing `Insight` schema with `insight_type` mapped:
  - recurring_vendors  → "trend"
  - pricing_anomalies  → "risk"
  - expirations        → "risk"

The downstream consumer (frontend, exports, chat) can't tell whether
a finding came from an LLM call or a pure function — they all share
the same shape and severity ladder.
"""
from __future__ import annotations

from mdi.brain.detectors.expirations import detect_expirations
from mdi.brain.detectors.pricing_anomalies import detect_pricing_anomalies
from mdi.brain.detectors.recurring_vendors import detect_recurring_vendors

__all__ = [
    "detect_expirations",
    "detect_pricing_anomalies",
    "detect_recurring_vendors",
]
