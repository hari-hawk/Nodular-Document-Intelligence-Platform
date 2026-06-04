"""Provider registry — both providers register, capability flags, missing-key behaviour."""
from __future__ import annotations

import pytest

from mdi.kernel.providers import (
    AnthropicProvider,
    GeminiProvider,
    ProviderError,
    ProviderNotConfigured,
    get_provider,
    list_providers,
)
from mdi.kernel.providers.base import reset_providers
from mdi.kernel.settings import get_settings


@pytest.fixture(autouse=True)
def _reset():
    reset_providers()
    get_settings.cache_clear()
    yield
    reset_providers()
    get_settings.cache_clear()


def test_both_providers_register():
    names = list_providers()
    assert "gemini" in names
    assert "anthropic" in names


def test_get_unknown_provider_raises():
    with pytest.raises(ProviderError):
        get_provider("openai")


def test_capabilities_advertised():
    g = get_provider("gemini")
    assert isinstance(g, GeminiProvider)
    assert g.supports_vision is True
    assert g.supports_json_mode is True

    a = get_provider("anthropic")
    assert isinstance(a, AnthropicProvider)
    assert a.supports_vision is True
    # Claude doesn't have JSON mode at the API level — we steer via the system prompt.
    assert a.supports_json_mode is False


@pytest.mark.asyncio
async def test_gemini_provider_raises_when_key_missing(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    get_settings.cache_clear()
    g = get_provider("gemini")
    with pytest.raises(ProviderNotConfigured):
        await g.call(
            model="gemini-2.5-flash",
            prompt="hi",
            system=None,
            images=[],
            json_mode=False,
            max_output_tokens=16,
            temperature=0.0,
        )


@pytest.mark.asyncio
async def test_anthropic_provider_raises_when_key_missing(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    get_settings.cache_clear()
    a = get_provider("anthropic")
    with pytest.raises(ProviderNotConfigured):
        await a.call(
            model="claude-sonnet-4-5",
            prompt="hi",
            system=None,
            images=[],
            json_mode=False,
            max_output_tokens=16,
            temperature=0.0,
        )
