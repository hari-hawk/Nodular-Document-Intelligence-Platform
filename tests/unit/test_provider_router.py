"""Provider router — chain semantics + DEFAULT_PROVIDER override."""
from __future__ import annotations

import pytest

from mdi.kernel import provider_router as pr
from mdi.kernel.settings import get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_chain_for_synthesis_is_gemini_then_claude(monkeypatch):
    monkeypatch.setenv("DEFAULT_PROVIDER", "auto")
    monkeypatch.setenv("GOOGLE_API_KEY", "fake")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
    get_settings.cache_clear()

    chain = pr.route_chain("synthesis")
    assert len(chain) == 2
    assert chain[0][0] == "gemini"
    assert chain[1][0] == "anthropic"
    assert "opus" in chain[1][1]   # synthesis fallback is Opus per the locked policy


def test_chain_for_perception_is_flash_then_haiku(monkeypatch):
    monkeypatch.setenv("DEFAULT_PROVIDER", "auto")
    monkeypatch.setenv("GOOGLE_API_KEY", "fake")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
    get_settings.cache_clear()

    chain = pr.route_chain("perception")
    assert chain[0] == ("gemini", "gemini-2.5-flash")
    assert chain[1][0] == "anthropic"
    assert "haiku" in chain[1][1]   # perception fallback is the cheap Claude tier


def test_route_returns_primary_only(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "fake")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
    get_settings.cache_clear()

    primary = pr.route("reasoning")
    assert primary[0] == "gemini"
    assert primary[1] == "gemini-2.5-pro"


def test_chain_filters_unconfigured_providers(monkeypatch):
    """If only Gemini is configured, the Anthropic fallback drops out of the chain."""
    monkeypatch.setenv("DEFAULT_PROVIDER", "auto")
    monkeypatch.setenv("GOOGLE_API_KEY", "fake")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    get_settings.cache_clear()

    chain = pr.route_chain("synthesis")
    assert len(chain) == 1
    assert chain[0][0] == "gemini"


def test_force_gemini_drops_fallback(monkeypatch):
    monkeypatch.setenv("DEFAULT_PROVIDER", "gemini")
    monkeypatch.setenv("GOOGLE_API_KEY", "fake")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
    get_settings.cache_clear()

    for tier in ("perception", "extraction", "reasoning", "synthesis"):
        chain = pr.route_chain(tier)  # type: ignore[arg-type]
        assert all(c[0] == "gemini" for c in chain)


def test_force_anthropic_drops_gemini(monkeypatch):
    monkeypatch.setenv("DEFAULT_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
    get_settings.cache_clear()

    for tier in ("perception", "extraction", "reasoning", "synthesis"):
        chain = pr.route_chain(tier)  # type: ignore[arg-type]
        assert all(c[0] == "anthropic" for c in chain)


def test_describe_returns_full_chains(monkeypatch):
    monkeypatch.setenv("DEFAULT_PROVIDER", "auto")
    monkeypatch.setenv("GOOGLE_API_KEY", "fake")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
    get_settings.cache_clear()

    desc = pr.describe()
    assert set(desc.keys()) == {"perception", "extraction", "reasoning", "synthesis"}
    assert all(len(chain) == 2 for chain in desc.values())
