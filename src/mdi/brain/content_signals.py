"""Content-signal pack detection — pre-LLM short-circuit (Wave 1.3).

For documents from a known vendor with a stable layout, paying an LLM
classify call is overkill. Digital-Direction handles this with
`first_page_signals` in carrier.yaml: regex / phrase markers on page 1
that, if matched, classify the document with near-100% precision and a
single string lookup.

MDI's port extends every pack's `skills.yaml` with an OPTIONAL
`content_signals:` block:

    content_signals:
      required_any:           # at least one of these must appear
        - "AT&T"
        - "at&t"
        - "att.com"
      doc_type_markers:       # phrases that imply a specific doc_type
        invoice:
          - "Bill-At-A-Glance"
          - "Billing Summary"
          - "TotalAmountDue"
        csr:
          - "CUSTOMER SERVICE RECORD"

Match semantics:
  - We scan only the first N pages (default: 2) of `IngestedDocument.text`.
    The vast majority of vendor / doc-type markers live in headers.
  - A pack matches when ANY entry in `required_any` is present.
  - The strongest doc_type_marker count wins the doc_type hint; a tie
    falls back to LLM classification.
  - Confidence is a coarse 3-tier ladder:
        any required_any match only          → 0.75 (vendor-confident, doc_type from LLM)
        required_any match + 1 doc_marker    → 0.90
        required_any match + 2+ doc_markers  → 0.95

  - Packs WITHOUT `content_signals` are silently ignored — the platform
    falls back to LLM classification, same as before this module existed.

Why not regex compile + share across packs? We compile per-pack at load
time and cache by pack-slug + signals-checksum. Across a batch of 100
documents from the same tenant, the per-pack compiled patterns are
reused. The build cost is one-time and bounded by `len(loaded_packs)`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from mdi.kernel.observability import get_logger

logger = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Match shape
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class SignalMatch:
    pack_slug: str
    confidence: float
    doc_type_hint: str | None
    matched_phrases: tuple[str, ...]
    rationale: str


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────
def detect_packs(
    *,
    text: str | None,
    available_packs: dict[str, dict[str, Any]],
    first_pages_text: str | None = None,
    min_confidence: float = 0.75,
) -> list[SignalMatch]:
    """Return all packs whose content_signals match the document text.

    Args:
      text: full document text (used as fallback if first_pages_text is None)
      available_packs: dict of {pack_slug: manifest_dict} — manifest must
        contain optional `content_signals` block to participate
      first_pages_text: pre-extracted first-2-page text if available;
        otherwise we use the first 8KB of `text` as a proxy
      min_confidence: drop matches below this threshold

    Returns:
      list of SignalMatch sorted by confidence DESC. Empty list if no
      pack has signals or no signals matched.

    The "multi-pattern recognition" requirement (Hari, 2026-06-04) lives
    here too: the caller gets ALL matches above threshold, not just the
    top one. Downstream consumers (Eyes, Pattern Cortex, the Patterns
    UI page) decide whether to act on one or all.
    """
    if not text and not first_pages_text:
        return []

    haystack = (first_pages_text or text or "")[:8000]
    matches: list[SignalMatch] = []

    for slug, manifest in available_packs.items():
        signals = (manifest or {}).get("content_signals")
        if not signals:
            continue
        match = _evaluate_pack(slug, signals, haystack)
        if match and match.confidence >= min_confidence:
            matches.append(match)

    matches.sort(key=lambda m: m.confidence, reverse=True)
    return matches


# ─────────────────────────────────────────────────────────────────────────────
# Per-pack evaluation
# ─────────────────────────────────────────────────────────────────────────────
def _evaluate_pack(
    slug: str,
    signals: dict[str, Any],
    haystack: str,
) -> SignalMatch | None:
    required_any: list[str] = signals.get("required_any") or []
    doc_type_markers: dict[str, list[str]] = signals.get("doc_type_markers") or {}

    matched_required: list[str] = [
        phrase for phrase in required_any
        if _phrase_matches(phrase, haystack)
    ]
    if not matched_required:
        return None  # vendor mark absent → not this pack

    # Find which doc_type has the most marker hits.
    doc_type_hits: dict[str, list[str]] = {}
    for doc_type, markers in doc_type_markers.items():
        hits = [m for m in markers if _phrase_matches(m, haystack)]
        if hits:
            doc_type_hits[doc_type] = hits

    if not doc_type_hits:
        return SignalMatch(
            pack_slug=slug,
            confidence=0.75,
            doc_type_hint=None,
            matched_phrases=tuple(matched_required),
            rationale=f"required_any matched {matched_required[:3]}; no doc_type marker",
        )

    # Highest hit-count wins.
    winner = max(doc_type_hits.items(), key=lambda kv: len(kv[1]))
    doc_type, hits = winner
    confidence = 0.95 if len(hits) >= 2 else 0.90

    return SignalMatch(
        pack_slug=slug,
        confidence=confidence,
        doc_type_hint=doc_type,
        matched_phrases=tuple(matched_required + hits),
        rationale=(
            f"required_any matched {matched_required[:3]}; "
            f"doc_type={doc_type} markers={hits[:3]}"
        ),
    )


def _phrase_matches(phrase: str, haystack: str) -> bool:
    """Phrase match — case-insensitive substring by default.

    A phrase starting with `re:` is treated as a regex (escape hatch for
    structured codes like account-number formats). Phrases enclosed in
    forward slashes (/.../  or  /.../i  for case-insensitive) are also
    treated as regex, matching DD's carrier.yaml convention so config
    can be ported verbatim.
    """
    p = phrase.strip()
    if not p:
        return False

    # Pre-compiled cache — frozenset on the phrase string makes the
    # lru_cache key stable across calls.
    if p.startswith("re:"):
        return _regex_search(p[3:], haystack) is not None
    if p.startswith("/") and (p.endswith("/") or p.endswith("/i")):
        flags = re.IGNORECASE if p.endswith("/i") else 0
        body = p[1:-2] if p.endswith("/i") else p[1:-1]
        try:
            return re.search(body, haystack, flags) is not None
        except re.error:
            return False

    return p.lower() in haystack.lower()


@lru_cache(maxsize=512)
def _regex_search(pattern: str, haystack: str) -> re.Match | None:
    """Cached regex search. The cache key includes `haystack` which is
    bounded to 8KB by the caller, so the cache lookup is cheap and
    repeated regex compiles across the same batch are avoided."""
    try:
        return re.search(pattern, haystack, re.IGNORECASE)
    except re.error:
        return None


def clear_caches() -> None:
    """Test helper — drop the regex compile cache."""
    _regex_search.cache_clear()
