"""Narrator — one-paragraph plain-English executive summary (Stage 15).

LLM-narrated when a gateway is provided; falls back to a deterministic
template otherwise so reports always have a summary.
"""
from __future__ import annotations

from mdi.kernel.llm_gateway import GatewayLike
from mdi.kernel.observability import get_logger
from mdi.models.schemas import (
    AccountBriefing,
    Anomaly,
    Insight,
)

logger = get_logger(__name__)

SYSTEM_PROMPT = """You are the executive narrator. Given the structured analytics for one
processing batch, write ONE concise paragraph (<= 120 words) for a busy executive.
Lead with the most material finding. Plain English; no markdown; no bullet points."""


def _heuristic_summary(
    n_documents: int,
    insights: list[Insight],
    anomalies: list[Anomaly],
    briefings: list[AccountBriefing],
) -> str:
    parts: list[str] = [f"Processed {n_documents} document(s)."]
    high_a = sum(1 for a in anomalies if a.severity == "HIGH")
    if high_a:
        parts.append(f"{high_a} HIGH-severity anomalies need immediate attention.")
    high_i = [i for i in insights if i.severity == "HIGH"]
    if high_i:
        parts.append(f"Top insight: {high_i[0].title}.")
    if briefings:
        with_short = sum(1 for b in briefings if b.money.shortfall)
        with_over = sum(1 for b in briefings if b.money.overpayment)
        if with_short or with_over:
            parts.append(
                f"{with_short} account(s) with shortfall, {with_over} with overpayment."
            )
    if len(parts) == 1:
        parts.append("No high-severity findings; routine batch.")
    return " ".join(parts)


async def narrate(
    *,
    n_documents: int,
    insights: list[Insight],
    anomalies: list[Anomaly],
    briefings: list[AccountBriefing],
    gateway: GatewayLike | None = None,
) -> str:
    fallback = _heuristic_summary(n_documents, insights, anomalies, briefings)
    if gateway is None:
        return fallback

    prompt_lines = [
        f"Documents processed: {n_documents}",
        f"Anomalies (HIGH/MED/LOW): "
        f"{sum(1 for a in anomalies if a.severity == 'HIGH')}/"
        f"{sum(1 for a in anomalies if a.severity == 'MEDIUM')}/"
        f"{sum(1 for a in anomalies if a.severity == 'LOW')}",
        f"Top insights: {', '.join(i.title for i in insights[:3]) or '(none)'}",
        f"Briefings: {len(briefings)}",
    ]
    try:
        resp = await gateway.generate(
            organ="narrator",
            tier="synthesis",
            system=SYSTEM_PROMPT,
            prompt="\n".join(prompt_lines),
            json_mode=False,
            max_output_tokens=1024,
            temperature=0.3,
        )
        return resp.text.strip() or fallback
    except Exception as e:
        logger.warning("narrator.gateway_error", error=str(e))
        return fallback
