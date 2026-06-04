"""Provider router — primary + fallback chain per organ tier.

Each tier maps to an ordered list of `(provider, model_id)` candidates.
The first that's configured (and reachable at call time) serves the
request; the gateway walks down the chain on retryable failures.

This file is the **only** place in the codebase that maps "what an organ
needs" to "which provider+model executes it". Edit `_POLICY` to reshape
the platform's provider behaviour.

Capability tiers:

  ┌────────────┬────────────────────────────────────────────────────────┐
  │ Tier       │ Used by (organs)                                       │
  ├────────────┼────────────────────────────────────────────────────────┤
  │ perception │ Eyes — fast classification, low temperature            │
  │ extraction │ Hands — multimodal (vision), structured JSON output    │
  │ reasoning  │ Pattern Cortex, Conscience.invent — long-context       │
  │ synthesis  │ Insight Cortex narration, Narrator, Chat — prose       │
  └────────────┴────────────────────────────────────────────────────────┘

LOCKED POLICY (Hari, 2026-05-07): Gemini-primary with Claude fallback.
Synthesis + reasoning tiers use Opus as the fallback (highest quality
when narrative or rule rigor matters). Perception/extraction fall back
to cheaper Claude tiers since those calls are high-volume.
"""
from __future__ import annotations

from typing import Literal

from mdi.kernel.observability import get_logger
from mdi.kernel.settings import get_settings

logger = get_logger(__name__)

OrganTier = Literal["perception", "extraction", "reasoning", "synthesis"]


# ===========================================================================
# THE POLICY (locked — Hari 2026-05-07)
# ---------------------------------------------------------------------------
# Each tier is a list of (provider, model_id) tuples. Index 0 is the
# primary; later entries are tried in order when the primary errors out
# on a retryable category (rate limit, 5xx, timeout, network).
#
# Model strings here are placeholders that get rewritten from settings
# at lookup time so env overrides work without a code change. See
# `_resolve_alias()` below.
# ===========================================================================
_POLICY: dict[OrganTier, list[tuple[str, str]]] = {
    "perception":  [("gemini", "@flash"), ("anthropic", "@haiku")],   # cheap → cheap
    "extraction":  [("gemini", "@flash"), ("anthropic", "@sonnet")],  # vision-capable fallback
    "reasoning":   [("gemini", "@pro"),   ("anthropic", "@opus")],    # rule invention quality
    "synthesis":   [("gemini", "@pro"),   ("anthropic", "@opus")],    # narrator/chat polish
}


def _resolve_alias(provider: str, model_or_alias: str) -> str:
    """Translate '@flash' / '@pro' / '@haiku' / etc. via settings."""
    if not model_or_alias.startswith("@"):
        return model_or_alias
    s = get_settings()
    table = {
        ("gemini",   "@flash"):  s.gemini_model_flash,
        ("gemini",   "@pro"):    s.gemini_model_pro,
        ("anthropic", "@haiku"):  s.claude_model_haiku,
        ("anthropic", "@sonnet"): s.claude_model_sonnet,
        ("anthropic", "@opus"):   s.claude_model_opus,
    }
    return table.get((provider, model_or_alias), model_or_alias)


def _key_for_provider(provider: str) -> str:
    s = get_settings()
    if provider == "gemini":
        return s.google_api_key
    if provider == "anthropic":
        return s.anthropic_api_key
    return ""


# ---------------------------------------------------------------------------
# Public API — used by LLMGateway and operators
# ---------------------------------------------------------------------------
def route_chain(tier: OrganTier) -> list[tuple[str, str]]:
    """Return the ordered (provider, model) chain for `tier`, filtered to
    providers whose API keys are present. Honours `DEFAULT_PROVIDER`:

      * 'auto'       — full chain (default)
      * 'gemini'     — Gemini-only, no fallback
      * 'anthropic'  — Anthropic-only, no fallback
    """
    s = get_settings()
    pref = s.default_provider.lower().strip()

    raw = [(p, _resolve_alias(p, m)) for p, m in _POLICY[tier]]

    if pref == "gemini":
        raw = [c for c in raw if c[0] == "gemini"]
    elif pref == "anthropic":
        raw = [c for c in raw if c[0] == "anthropic"]

    configured = [c for c in raw if _key_for_provider(c[0])]
    if not configured:
        # Nothing configured — return the head anyway so the provider raises
        # a clear ProviderNotConfigured.
        logger.warning(
            "router.no_configured_candidates",
            tier=tier,
            chain=[f"{p}/{m}" for p, m in raw],
        )
        return raw or [("gemini", _resolve_alias("gemini", "@flash"))]
    return configured


def route(tier: OrganTier) -> tuple[str, str]:
    """Return only the primary candidate (back-compat helper)."""
    return route_chain(tier)[0]


def describe() -> dict[str, list[tuple[str, str]]]:
    """Diagnostic — what each tier currently routes to (full chain)."""
    return {
        tier: route_chain(tier)  # type: ignore[arg-type]
        for tier in ("perception", "extraction", "reasoning", "synthesis")
    }
