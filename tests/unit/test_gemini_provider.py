"""Unit tests for the new google-genai backed Gemini provider.

The SDK itself is mocked — these tests don't hit any network. They
verify:
  - AI Studio path is selected when only `google_api_key` is set
  - Vertex AI path is selected when `vertex_project` is set
  - Vision calls get promoted to the vision model
  - Errors from the SDK surface as ProviderError (retryable)
  - Token usage flows through into ProviderCallResult
"""
from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mdi.kernel.providers.base import (
    ProviderError,
    ProviderNotConfigured,
    reset_providers,
)
from mdi.kernel.providers.gemini_provider import GeminiProvider
from mdi.kernel.settings import get_settings


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    """Clear the lru_cache on get_settings so env changes propagate."""
    get_settings.cache_clear()
    reset_providers()
    yield
    get_settings.cache_clear()
    reset_providers()


def _install_fake_genai(monkeypatch) -> tuple[MagicMock, MagicMock]:
    """Inject a fake `google.genai` module so the provider can import it
    without the real SDK being involved. Returns (Client_mock, response_mock).
    """
    response_mock = MagicMock()
    response_mock.text = '{"vendor": "Acme"}'
    response_mock.usage_metadata = types.SimpleNamespace(
        prompt_token_count=42, candidates_token_count=17,
    )

    async_models_mock = MagicMock()
    async_models_mock.generate_content = AsyncMock(return_value=response_mock)
    aio_mock = MagicMock(models=async_models_mock)

    client_instance = MagicMock()
    client_instance.aio = aio_mock
    client_class = MagicMock(return_value=client_instance)

    fake_genai_module = types.ModuleType("google.genai")
    fake_genai_module.Client = client_class  # type: ignore[attr-defined]

    fake_types_module = types.ModuleType("google.genai.types")

    class _Part:
        @staticmethod
        def from_bytes(*, data, mime_type):
            return ("PART", mime_type, len(data))

    class _GenerateContentConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    fake_types_module.Part = _Part  # type: ignore[attr-defined]
    fake_types_module.GenerateContentConfig = _GenerateContentConfig  # type: ignore[attr-defined]
    fake_genai_module.types = fake_types_module  # type: ignore[attr-defined]

    # Make `from google import genai` resolve to our fake.
    google_pkg = types.ModuleType("google")
    google_pkg.genai = fake_genai_module  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "google", google_pkg)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai_module)
    monkeypatch.setitem(sys.modules, "google.genai.types", fake_types_module)

    return client_class, response_mock


@pytest.mark.asyncio
async def test_ai_studio_path_used_when_no_vertex_project(monkeypatch):
    """With only GOOGLE_API_KEY set, the provider must construct an
    AI Studio Client (no `vertexai=True` kwarg)."""
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-key")
    monkeypatch.delenv("VERTEX_PROJECT", raising=False)
    client_class, _ = _install_fake_genai(monkeypatch)

    p = GeminiProvider()
    result = await p.call(
        model="gemini-2.5-flash", prompt="hi", system=None,
        images=[], json_mode=True, max_output_tokens=512, temperature=0.0,
    )

    # Client constructed with api_key kwarg, NOT vertexai=True
    assert client_class.call_count == 1
    kwargs = client_class.call_args.kwargs
    assert kwargs == {"api_key": "fake-key"}
    assert result.text == '{"vendor": "Acme"}'
    assert (result.input_tokens, result.output_tokens) == (42, 17)


@pytest.mark.asyncio
async def test_vertex_path_used_when_project_set(monkeypatch):
    """When VERTEX_PROJECT is set, the Client gets `vertexai=True` plus
    project + location — never the api_key kwarg."""
    monkeypatch.setenv("VERTEX_PROJECT", "my-gcp-project")
    monkeypatch.setenv("VERTEX_LOCATION", "us-east5")
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-key")  # should be ignored
    client_class, _ = _install_fake_genai(monkeypatch)

    p = GeminiProvider()
    await p.call(
        model="gemini-2.5-pro", prompt="hi", system=None,
        images=[], json_mode=False, max_output_tokens=None, temperature=0.0,
    )

    kwargs = client_class.call_args.kwargs
    assert kwargs.get("vertexai") is True
    assert kwargs.get("project") == "my-gcp-project"
    assert kwargs.get("location") == "us-east5"
    assert "api_key" not in kwargs


@pytest.mark.asyncio
async def test_vision_call_promotes_flash_to_pro(monkeypatch):
    """When images are present and the requested model is Flash, the
    provider promotes to Pro (which has stronger vision performance)."""
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-key")
    monkeypatch.delenv("GEMINI_VISION_MODEL", raising=False)
    _, _ = _install_fake_genai(monkeypatch)

    # Capture which model the SDK was called with.
    captured: dict = {}
    async def fake_generate(**kwargs):
        captured.update(kwargs)
        resp = MagicMock()
        resp.text = "ok"
        resp.usage_metadata = types.SimpleNamespace(prompt_token_count=1, candidates_token_count=1)
        return resp

    p = GeminiProvider()
    with patch.object(p, "_build_client") as build:
        client = MagicMock()
        client.aio.models.generate_content = AsyncMock(side_effect=fake_generate)
        build.return_value = client

        await p.call(
            model="gemini-2.5-flash", prompt="describe this", system=None,
            images=[b"\x89PNG\r\n\x1a\n" + b"\x00" * 32],  # fake 1-byte image
            json_mode=False, max_output_tokens=256, temperature=0.0,
        )

    # Default vision model is whatever gemini_model_pro is set to (2.5-pro).
    assert captured["model"] == "gemini-2.5-pro"
    # Image got translated into a Part tuple by our fake types.Part.
    parts = captured["contents"]
    assert parts[0] == "describe this"
    assert parts[1][0] == "PART"
    assert parts[1][1] == "image/png"


@pytest.mark.asyncio
async def test_missing_creds_raises_provider_not_configured(monkeypatch):
    """With no API key and no Vertex project, calling the provider must
    raise ProviderNotConfigured rather than masking the misconfig."""
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    monkeypatch.delenv("VERTEX_PROJECT", raising=False)
    _install_fake_genai(monkeypatch)

    p = GeminiProvider()
    with pytest.raises(ProviderNotConfigured):
        await p.call(
            model="gemini-2.5-flash", prompt="hi", system=None,
            images=[], json_mode=False, max_output_tokens=None, temperature=0.0,
        )


@pytest.mark.asyncio
async def test_none_token_counts_coerced_to_zero(monkeypatch):
    """The new google-genai SDK can return usage_metadata with None-valued
    token counts (observed on safety-filtered responses). Downstream cost
    math does `tokens / 1_000_000` which throws on None — the provider
    must coerce None to 0 so a safety-filtered call doesn't crash the
    pipeline (the response.text is still returned). Regression guard for
    a bug introduced + fixed in Wave 1.6 of the DD uplift."""
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-key")
    monkeypatch.delenv("VERTEX_PROJECT", raising=False)
    _install_fake_genai(monkeypatch)

    # Simulate the SDK returning usage_metadata.candidates_token_count = None
    response_with_none = MagicMock()
    response_with_none.text = ""
    response_with_none.usage_metadata = types.SimpleNamespace(
        prompt_token_count=12,
        candidates_token_count=None,  # ← the actual bug surface
    )

    p = GeminiProvider()
    with patch.object(p, "_build_client") as build:
        client = MagicMock()
        client.aio.models.generate_content = AsyncMock(return_value=response_with_none)
        build.return_value = client

        result = await p.call(
            model="gemini-2.5-flash", prompt="hi", system=None,
            images=[], json_mode=False, max_output_tokens=None, temperature=0.0,
        )

    # None coerced to 0; the result is still usable downstream.
    assert result.input_tokens == 12
    assert result.output_tokens == 0
    # And the value is a real int, not None, so estimate_cost_usd works.
    assert isinstance(result.output_tokens, int)


@pytest.mark.asyncio
async def test_sdk_error_wrapped_as_provider_error(monkeypatch):
    """Any exception from the SDK gets surfaced as ProviderError — which
    is in the retryable_exceptions set so the gateway retries / falls
    back to the next provider in the chain."""
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-key")
    monkeypatch.delenv("VERTEX_PROJECT", raising=False)
    _install_fake_genai(monkeypatch)

    p = GeminiProvider()
    with patch.object(p, "_build_client") as build:
        client = MagicMock()
        client.aio.models.generate_content = AsyncMock(
            side_effect=RuntimeError("simulated 503"),
        )
        build.return_value = client

        with pytest.raises(ProviderError) as exc_info:
            await p.call(
                model="gemini-2.5-flash", prompt="hi", system=None,
                images=[], json_mode=False, max_output_tokens=None, temperature=0.0,
            )

    assert "simulated 503" in str(exc_info.value)
    # And it's in the retryable set.
    assert ProviderError in p.retryable_exceptions()
