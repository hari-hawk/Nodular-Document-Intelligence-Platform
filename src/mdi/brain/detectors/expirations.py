"""Expirations — contracts/services with due_date approaching.

Walks extractions for any `due_date` / `expiration_date` field and
surfaces:
  - already expired  → HIGH (an expired contract billing is a real problem)
  - <30 days out      → MEDIUM (renewal-window action item)
  - 30-90 days out    → INFO (heads-up; usually not actionable yet)

Date parsing is permissive — ISO-8601 first, then a few common
fallbacks (MM/DD/YYYY, "April 30, 2026"). When all parsers fail the
value is skipped rather than failing the whole detector.
"""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from mdi.models.schemas import Cluster, Extraction, Insight

# Canonical date fields (after Wave 1.x aliasing). expiration_date is
# already aliased to due_date in _canonical_fields.ALIASES, so checking
# `due_date` covers both.
_DATE_FIELDS = frozenset({"due_date", "contract_end_date", "valid_until"})

# Severity bucket boundaries — days from today.
_EXPIRED_HIGH = 0
_NEAR_MEDIUM = 30
_HEADS_UP_INFO = 90


def detect_expirations(
    clusters: dict[uuid.UUID, Cluster],
    extractions: dict[uuid.UUID, Extraction],
    *,
    today: date | None = None,
) -> list[Insight]:
    """Return one finding per document with an upcoming or past due_date.

    Args:
      today: override for testing — defaults to date.today().
    """
    today = today or datetime.now(UTC).date()
    findings: list[Insight] = []

    for doc_id, ex in extractions.items():
        cluster = clusters.get(doc_id)
        vendor = cluster.vendor if cluster else "unknown"
        for field_name in _DATE_FIELDS:
            field = ex.fields.get(field_name)
            if not field:
                continue
            raw = field.value if hasattr(field, "value") else field
            parsed = _parse_date(raw)
            if parsed is None:
                continue
            days = (parsed - today).days

            if days < _EXPIRED_HIGH:
                severity = "HIGH"
                title = (
                    f"{vendor}: {field_name} ({parsed.isoformat()}) is "
                    f"{abs(days)} days PAST"
                )
                body = (
                    "This document references a date in the past. If it's a "
                    "contract end date, the agreement is expired and any active "
                    "billing under it is out-of-contract — flag to the customer "
                    "team immediately."
                )
            elif days <= _NEAR_MEDIUM:
                severity = "MEDIUM"
                title = (
                    f"{vendor}: {field_name} ({parsed.isoformat()}) is "
                    f"{days} days away"
                )
                body = (
                    "Inside the 30-day renewal/action window. Consider opening "
                    "a renewal task or confirming the customer's intent."
                )
            elif days <= _HEADS_UP_INFO:
                severity = "INFO"
                title = (
                    f"{vendor}: {field_name} ({parsed.isoformat()}) in {days} days"
                )
                body = (
                    "Inside the 90-day heads-up window. Not urgent; useful "
                    "context when prioritising the renewal pipeline."
                )
            else:
                continue  # too far out to surface

            findings.append(Insight(
                insight_type="risk",
                severity=severity,  # type: ignore[arg-type]
                title=title,
                body=body,
                evidence=[],
                affected_documents=[doc_id],
            ))

    return findings


# ─────────────────────────────────────────────────────────────────────────────
# Permissive date parsing — tries ISO first, then a few common formats.
# ─────────────────────────────────────────────────────────────────────────────
_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%d %B %Y",
    "%d %b %Y",
)


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    s = str(value).strip()
    if not s:
        return None
    for fmt in _FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    # Last-ditch fromisoformat (handles `2026-04-30T00:00:00` shapes).
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None
