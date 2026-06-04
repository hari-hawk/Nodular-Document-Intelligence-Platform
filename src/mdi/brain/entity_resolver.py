"""Entity resolver — fuzzy matching with audit trail (per locked decision).

Two thresholds:
  >= AUTO_THRESHOLD       — auto-merge, audit logged
  >= REVIEW_THRESHOLD     — propose merge, requires analyst confirmation
  <  REVIEW_THRESHOLD     — keep separate

Default thresholds come from `settings.entity_resolver_threshold`
(applied as the AUTO threshold; REVIEW = AUTO - 5).
"""
from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz, process

from mdi.kernel.observability import get_logger
from mdi.kernel.settings import get_settings

logger = get_logger(__name__)


@dataclass
class MatchProposal:
    candidate: str
    score: float
    decision: str  # "auto", "review", "reject"


def propose_match(
    target: str,
    candidates: list[str],
    *,
    auto_threshold: int | None = None,
    review_margin: int = 5,
) -> MatchProposal | None:
    if not candidates:
        return None
    auto = auto_threshold if auto_threshold is not None else get_settings().entity_resolver_threshold
    review = max(auto - review_margin, 0)

    best = process.extractOne(target, candidates, scorer=fuzz.token_set_ratio)
    if best is None:
        return None
    name, score, _ = best
    decision = "reject"
    if score >= auto:
        decision = "auto"
    elif score >= review:
        decision = "review"
    return MatchProposal(candidate=name, score=float(score), decision=decision)


def normalize_vendor_name(name: str) -> str:
    return " ".join(name.strip().split()).lower()
