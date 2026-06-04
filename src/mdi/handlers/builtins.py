"""Built-in handlers — the seed set that ships with MDI.

Two handlers are registered here at module import:

  recompute_total
    Re-sums line_items and compares to the printed total. Returns a
    HandlerResult flagging the discrepancy if the recomputed sum
    differs from the printed total by > $0.01.

  flag_for_review
    Records a manual review flag on the document. Useful when an
    analyst sees a pattern the auto-flow missed and wants it queued.

These are intentionally small, deterministic, and pack-agnostic.
Pack authors should add domain-specific handlers in their own pack's
init module (e.g. `mdi.packs.telecom.handlers`) and import that pack's
module at startup so the handlers self-register.
"""
from __future__ import annotations

from typing import Any

from mdi.handlers.registry import HandlerContext, HandlerResult, register


def _as_number(v: Any) -> float | None:
    """Defensively coerce a field value to float. Returns None on miss."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError):
        return None


@register(
    "recompute_total",
    description=(
        "Re-sum the document's line items and compare to the printed total. "
        "Flags a discrepancy when the recomputed sum diverges from the printed "
        "total by more than $0.01."
    ),
    when_to_use=(
        "When a pricing anomaly is suspected, or when an analyst doubts the "
        "extracted total. Works on any document with both `line_items` and "
        "`total` fields. Pure-deterministic — does not call the LLM."
    ),
)
async def recompute_total(ctx: HandlerContext) -> HandlerResult:
    fields = ctx.extraction or {}
    total_field = fields.get("total")
    items_field = fields.get("line_items")

    def _v(f):
        if isinstance(f, dict) and "value" in f:
            return f["value"]
        return f

    printed_total = _as_number(_v(total_field))
    items = _v(items_field) or []

    if printed_total is None:
        return HandlerResult(
            ok=False,
            output="document has no `total` field — nothing to recompute",
        )
    if not isinstance(items, list) or not items:
        return HandlerResult(
            ok=False,
            output="document has no `line_items` list — cannot recompute",
        )

    summed = 0.0
    used_keys: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        # Try common amount keys in order — the canonical aliases layer
        # collapses some of these but line_items inside a list aren't
        # canonicalised today, so we accept several.
        for key in ("amount", "total", "charge", "mrc_total",
                    "unit_price", "extended_price"):
            n = _as_number(item.get(key))
            if n is not None:
                summed += n
                if key not in used_keys:
                    used_keys.append(key)
                break

    delta = summed - printed_total
    matches = abs(delta) <= 0.01
    return HandlerResult(
        ok=True,
        output=(
            f"line_items sum to {summed:.2f}; printed total is "
            f"{printed_total:.2f}; delta {delta:+.2f} "
            f"({'match' if matches else 'MISMATCH'})"
        ),
        data={
            "printed_total": printed_total,
            "recomputed_total": round(summed, 2),
            "delta": round(delta, 2),
            "matches": matches,
            "amount_keys_used": used_keys,
            "n_items": len(items),
        },
    )


@register(
    "flag_for_review",
    description=(
        "Mark a document for manual analyst review. Adds the document_id "
        "(if provided) and the reason (from ctx.kwargs['reason']) to the "
        "side_effects list so the audit log can show what was queued."
    ),
    when_to_use=(
        "When the analyst (via chat) or a pattern wants a document escalated. "
        "The handler is a no-op on its own — the consumer downstream of the "
        "side_effects is what actually creates the review-queue row."
    ),
)
async def flag_for_review(ctx: HandlerContext) -> HandlerResult:
    reason = (ctx.kwargs or {}).get("reason") or "no reason given"
    doc_id_str = str(ctx.document_id) if ctx.document_id else "(no document_id)"
    return HandlerResult(
        ok=True,
        output=f"flagged {doc_id_str} for review: {reason}",
        data={"document_id": doc_id_str, "reason": reason},
        side_effects=[f"queue_review:{doc_id_str}:{reason[:80]}"],
    )
