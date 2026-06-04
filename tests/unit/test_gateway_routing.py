"""Gateway — tier-based routing + fallback chain semantics."""
from __future__ import annotations

import pytest

from mdi.kernel.llm_gateway import LLMGateway
from mdi.kernel.providers.base import (
    BaseProvider,
    ProviderCallResult,
    ProviderNotConfigured,
    register_provider,
    reset_providers,
)
from mdi.kernel.settings import get_settings


class _StubProvider(BaseProvider):
    """Records calls; can be configured to fail with a specific exception."""

    name = "stub"
    supports_vision = True
    supports_json_mode = True

    def __init__(self, *, fail_with: type[BaseException] | None = None,
                 raise_provider_not_configured: bool = False):
        self.calls: list[dict] = []
        self.fail_with = fail_with
        self.raise_pnc = raise_provider_not_configured

    async def call(self, **kwargs):
        self.calls.append(kwargs)
        if self.raise_pnc:
            raise ProviderNotConfigured("stub: missing key")
        if self.fail_with:
            raise self.fail_with("stub failure")
        return ProviderCallResult(text='{"ok": true}', raw=None, input_tokens=10, output_tokens=20)

    def retryable_exceptions(self):
        # We mark TimeoutError retryable; tests that want to bust the chain
        # use that, while ConnectionError is treated as non-retryable here
        # to keep the retry loop short during tests.
        return (TimeoutError,)


@pytest.fixture(autouse=True)
def _isolated_registry():
    reset_providers()
    get_settings.cache_clear()
    yield
    reset_providers()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_gateway_dispatches_to_tier_route(monkeypatch):
    """Primary chain entry serves the call when it succeeds."""
    primary = _StubProvider()
    register_provider("primary_synth", lambda: primary)

    from mdi.kernel import provider_router as pr
    saved = dict(pr._POLICY)
    pr._POLICY["synthesis"] = [("primary_synth", "stub-primary")]
    monkeypatch.setenv("DEFAULT_PROVIDER", "auto")
    monkeypatch.setenv("GOOGLE_API_KEY", "fake")    # so the chain treats us as configured
    get_settings.cache_clear()

    try:
        gw = LLMGateway()
        resp = await gw.generate(organ="narrator", tier="synthesis",
                                 prompt="summarise", system=None,
                                 json_mode=False, max_output_tokens=64)
    finally:
        pr._POLICY.clear()
        pr._POLICY.update(saved)

    assert resp.call.model == "stub-primary"
    assert resp.text == '{"ok": true}'
    assert len(primary.calls) == 1


@pytest.mark.asyncio
async def test_gateway_falls_back_when_primary_unconfigured(monkeypatch):
    """Primary raises ProviderNotConfigured → fallback serves the call."""
    primary = _StubProvider(raise_provider_not_configured=True)
    fallback = _StubProvider()
    register_provider("primary_fb", lambda: primary)
    register_provider("fallback_fb", lambda: fallback)

    from mdi.kernel import provider_router as pr
    saved = dict(pr._POLICY)
    pr._POLICY["synthesis"] = [
        ("primary_fb", "primary-model"),
        ("fallback_fb", "fallback-model"),
    ]
    monkeypatch.setenv("DEFAULT_PROVIDER", "auto")
    monkeypatch.setenv("GOOGLE_API_KEY", "fake")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
    get_settings.cache_clear()

    # Bypass the router's own configured-only filter by registering custom names
    # that always pass (they're neither "gemini" nor "anthropic" so the filter
    # treats them as configured).
    try:
        gw = LLMGateway()
        resp = await gw.generate(organ="narrator", tier="synthesis",
                                 prompt="x", system=None, json_mode=False)
    finally:
        pr._POLICY.clear()
        pr._POLICY.update(saved)

    assert resp.call.model == "fallback-model"
    assert len(primary.calls) == 1   # primary was attempted
    assert len(fallback.calls) == 1  # fallback succeeded


@pytest.mark.asyncio
async def test_gateway_raises_when_chain_exhausted(monkeypatch):
    """All chain candidates fail → original exception surfaces."""
    primary = _StubProvider(raise_provider_not_configured=True)
    fallback = _StubProvider(raise_provider_not_configured=True)
    register_provider("p1", lambda: primary)
    register_provider("p2", lambda: fallback)

    from mdi.kernel import provider_router as pr
    saved = dict(pr._POLICY)
    pr._POLICY["reasoning"] = [("p1", "m1"), ("p2", "m2")]
    monkeypatch.setenv("GOOGLE_API_KEY", "fake")
    get_settings.cache_clear()

    try:
        gw = LLMGateway()
        with pytest.raises(ProviderNotConfigured):
            await gw.generate(organ="x", tier="reasoning", prompt="y", system=None)
    finally:
        pr._POLICY.clear()
        pr._POLICY.update(saved)


@pytest.mark.asyncio
async def test_gateway_explicit_provider_skips_fallback(monkeypatch):
    """Explicit provider+model = single-element chain; no fallback attempted."""
    explicit = _StubProvider()
    register_provider("explicit_only", lambda: explicit)
    monkeypatch.setenv("GOOGLE_API_KEY", "fake")
    get_settings.cache_clear()

    gw = LLMGateway()
    resp = await gw.generate(organ="custom", provider="explicit_only", model="my-model",
                             prompt="hello", system=None, json_mode=False)
    assert resp.call.model == "my-model"
    assert len(explicit.calls) == 1


@pytest.mark.asyncio
async def test_gateway_rejects_neither_tier_nor_explicit_pair():
    gw = LLMGateway()
    with pytest.raises(ValueError, match="tier"):
        await gw.generate(organ="x", prompt="y")
