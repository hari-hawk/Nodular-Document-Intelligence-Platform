"""Provider fallback chain — Gemini → Claude.

When the primary provider (Gemini) becomes unconfigured mid-process, the
router's chain should still resolve and Claude should serve every organ
call. We simulate the outage by blanking GOOGLE_API_KEY for the duration
of this test.

Cost budget: ~$0.05 (Claude is ~5× Gemini per call, but only 1 doc).
"""
from __future__ import annotations

import asyncio
import os

import pytest

from tests.live_llm.conftest import TENANT_A

pytestmark = pytest.mark.live_llm


def test_chain_falls_back_to_claude_when_gemini_unconfigured(
    fresh_db, reset_runtime, monkeypatch, cross_industry_corpus,
) -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set — fallback test requires Claude")

    # Simulate Gemini outage by blanking the key.
    monkeypatch.setenv("GOOGLE_API_KEY", "")

    # The settings cache has to be cleared AFTER the env mutation so the new
    # value propagates to provider_router.route_chain.
    from mdi.brain.hippocampus import Hippocampus
    from mdi.kernel.auth import reset_engine
    from mdi.kernel.llm_gateway import reset_gateway
    from mdi.kernel.providers.base import reset_providers
    from mdi.kernel.settings import get_settings
    from mdi.orchestrator.pipeline import run_batch_async

    get_settings.cache_clear()
    reset_providers()
    reset_gateway()
    reset_engine()

    # Sanity: the router chain should resolve to anthropic for every tier.
    from mdi.kernel import provider_router as pr
    for tier in ("perception", "extraction", "reasoning", "synthesis"):
        chain = pr.route_chain(tier)  # type: ignore[arg-type]
        assert chain[0][0] == "anthropic", (
            f"with empty GOOGLE_API_KEY, tier={tier} primary must be anthropic, "
            f"got {chain[0]}"
        )

    # Run one doc end-to-end.
    payloads = cross_industry_corpus[:1]  # smallest possible to keep cost down
    report = asyncio.run(
        run_batch_async(
            tenant_id=str(TENANT_A),
            payloads=payloads,
            hippocampus=Hippocampus(use_real_embeddings=False),
            persist=True,
        )
    )

    # Pipeline should have completed.
    assert len(report["documents"]) == 1
    assert report["total_cost_usd"] > 0

    # Every organ that issued an LLM call should have hit Anthropic, not Gemini.
    from mdi.kernel.llm_gateway import get_gateway
    gw = get_gateway()
    organs_used = [(c.organ, c.model) for c in gw.cost_tracker.events]
    assert organs_used, "no LLM calls recorded"
    for organ, model in organs_used:
        assert "claude" in model.lower(), (
            f"organ {organ} hit {model!r} but Gemini was unconfigured — "
            f"chain should have routed to Claude"
        )

    print(f"\n[fallback] {len(organs_used)} LLM calls all on Claude; "
          f"cost: ${report['total_cost_usd']:.5f}")
