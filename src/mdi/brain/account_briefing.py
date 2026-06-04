"""Account Briefing — per-group reconciliation (Stage 14)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from mdi.models.schemas import (
    AccountBriefing,
    ActionItem,
    Cluster,
    DocumentGroup,
    Extraction,
    MoneyPicture,
    TimelineEvent,
)


def _money_value(ex: Extraction, key: str) -> float | None:
    f = ex.fields.get(key)
    if f is None or f.value is None:
        return None
    try:
        return float(f.value)
    except (TypeError, ValueError):
        return None


def _date_value(ex: Extraction, key: str) -> datetime | None:
    f = ex.fields.get(key)
    if f is None or f.value is None:
        return None
    raw = f.value
    if isinstance(raw, datetime):
        return raw
    try:
        return datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None


def brief(
    group: DocumentGroup,
    extractions: dict[str, Extraction],
    clusters: dict[str, Cluster],
) -> AccountBriefing:
    committed: float | None = None
    billed = 0.0
    paid = 0.0
    timeline: list[TimelineEvent] = []
    risk_flags: list[str] = []
    actions: list[ActionItem] = []
    seen_currency = "USD"

    for did in group.document_ids:
        ex = extractions.get(str(did))
        c = clusters.get(str(did))
        if ex is None or c is None:
            continue
        amount = _money_value(ex, "total")
        cur_field = ex.fields.get("currency")
        if cur_field and cur_field.value:
            seen_currency = str(cur_field.value)
        when = _date_value(ex, "document_date") or _date_value(ex, "due_date")
        if when:
            timeline.append(
                TimelineEvent(
                    occurred_at=when.replace(tzinfo=when.tzinfo or timezone.utc),
                    description=f"{c.doc_type} from {c.vendor}",
                    document_id=did,
                )
            )
        if c.doc_type.startswith("contract"):
            committed = amount
        elif c.doc_type in {"invoice", "statement"} and amount is not None:
            billed += amount
        elif c.doc_type == "receipt" and amount is not None:
            paid += amount

    timeline.sort(key=lambda t: t.occurred_at)

    shortfall = None
    overpayment = None
    if committed is not None:
        if billed and billed < committed * 0.9:
            shortfall = committed - billed
            risk_flags.append("billed_below_committed")
            actions.append(
                ActionItem(
                    severity="MEDIUM",
                    title="Billed below committed",
                    detail=f"Shortfall of {shortfall:.2f} {seen_currency}",
                )
            )
        if billed and billed > committed * 1.1:
            overpayment = billed - committed
            risk_flags.append("billed_above_committed")
            actions.append(
                ActionItem(
                    severity="HIGH",
                    title="Billed above committed",
                    detail=f"Overage of {overpayment:.2f} {seen_currency} - review with vendor",
                )
            )

    if billed and paid and paid < billed * 0.95:
        actions.append(
            ActionItem(
                severity="MEDIUM",
                title="Outstanding balance",
                detail=f"Paid {paid:.2f} of {billed:.2f} {seen_currency}",
            )
        )

    return AccountBriefing(
        group_id=group.group_id,
        money=MoneyPicture(
            committed=committed,
            billed=billed or None,
            paid=paid or None,
            currency=seen_currency,
            shortfall=shortfall,
            overpayment=overpayment,
        ),
        timeline=timeline,
        actions=actions,
        risk_flags=risk_flags,
    )


def brief_all(
    groups: list[DocumentGroup],
    extractions: dict[str, Extraction],
    clusters: dict[str, Cluster],
) -> list[AccountBriefing]:
    return [brief(g, extractions, clusters) for g in groups]


_ = Any  # re-export anchor for type checkers if module is imported via *
