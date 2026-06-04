"""Google Gemini adapter — new `google-genai` SDK (2.x).

Migrated from the deprecated `google.generativeai` package. The new SDK
supports BOTH AI Studio (api_key auth) and Vertex AI (ADC / service
account auth) through a single `Client` — selected here by env:

    vertex_project=""                   → AI Studio (legacy default)
    vertex_project="my-gcp-project"     → Vertex AI

Vision (VLM) inputs are passed as ``types.Part.from_bytes(...)`` parts in
the request. The router already flips ``IngestedDocument.needs_vision``
based on mime type / heuristics; this provider routes any call with
non-empty ``images`` through the vision-capable model
(``settings.gemini_vision_model`` if set, else ``gemini_model_pro``).

Lazy-imports the SDK so test environments without the package can still
load this module via FakeGateway.
"""
from __future__ import annotations

import asyncio
from typing import Any

from mdi.kernel.providers.base import (
    BaseProvider,
    ProviderCallResult,
    ProviderError,
    ProviderNotConfigured,
    register_provider,
)
from mdi.kernel.settings import get_settings


class GeminiProvider(BaseProvider):
    name = "gemini"
    supports_vision = True
    supports_json_mode = True
    supports_tools = True

    def _build_client(self) -> Any:
        """Construct a google.genai Client targeting AI Studio or Vertex.

        Imported lazily so the test harness doesn't pay the SDK import
        cost (and so a missing dependency on a stripped image errors at
        call time, not module import).
        """
        s = get_settings()
        from google import genai  # type: ignore[import-not-found]

        if s.vertex_project:
            # Vertex AI path — IAM auth via ADC or explicit service-account JSON.
            kwargs: dict[str, Any] = {
                "vertexai": True,
                "project": s.vertex_project,
                "location": s.vertex_location,
            }
            if s.vertex_credentials_path:
                # The SDK reads GOOGLE_APPLICATION_CREDENTIALS from the env if
                # set, so we surface the configured path the same way without
                # forcing the caller to also export it shell-side.
                import os
                os.environ.setdefault(
                    "GOOGLE_APPLICATION_CREDENTIALS", s.vertex_credentials_path,
                )
            return genai.Client(**kwargs)

        # AI Studio path — api_key auth (matches the legacy provider behaviour).
        if not s.google_api_key:
            raise ProviderNotConfigured(
                "Neither vertex_project nor google_api_key is set. "
                "Set GOOGLE_API_KEY for AI Studio, or VERTEX_PROJECT for Vertex AI."
            )
        return genai.Client(api_key=s.google_api_key)

    def _select_model(self, requested: str, has_images: bool) -> str:
        """Vision calls get redirected to the vision-capable model when
        the caller asked for an alias that doesn't have a vision tier."""
        if not has_images:
            return requested
        s = get_settings()
        if s.gemini_vision_model:
            return s.gemini_vision_model
        # Gemini 2.5 Flash + Pro both handle images, but Pro is more reliable
        # on layout-heavy / multi-page scans. Promote Flash → Pro for vision.
        if requested == s.gemini_model_flash:
            return s.gemini_model_pro
        return requested

    async def call(
        self,
        *,
        model: str,
        prompt: str,
        system: str | None,
        images: list[bytes],
        json_mode: bool,
        max_output_tokens: int | None,
        temperature: float,
    ) -> ProviderCallResult:
        client = self._build_client()
        effective_model = self._select_model(model, has_images=bool(images))

        from google.genai import types  # type: ignore[import-not-found]

        # Build the parts list: prompt text first, then any inline images.
        parts: list[Any] = [prompt]
        for blob in images:
            parts.append(types.Part.from_bytes(data=blob, mime_type="image/png"))

        config_kwargs: dict[str, Any] = {
            "temperature": temperature,
            "max_output_tokens": max_output_tokens or 4096,
            "response_mime_type": "application/json" if json_mode else "text/plain",
        }
        if system:
            config_kwargs["system_instruction"] = system

        try:
            # The SDK exposes an async surface via ``client.aio``; we use it
            # so we don't block the event loop. asyncio.to_thread is the
            # fallback if the installed SDK version is sync-only.
            if hasattr(client, "aio"):
                resp = await client.aio.models.generate_content(
                    model=effective_model,
                    contents=parts,
                    config=types.GenerateContentConfig(**config_kwargs),
                )
            else:
                resp = await asyncio.to_thread(
                    client.models.generate_content,
                    model=effective_model,
                    contents=parts,
                    config=types.GenerateContentConfig(**config_kwargs),
                )
        except Exception as exc:
            raise ProviderError(f"gemini call failed: {exc}") from exc

        text = getattr(resp, "text", "") or ""
        usage = getattr(resp, "usage_metadata", None)
        # The new google-genai SDK occasionally returns `usage_metadata`
        # with None-valued token fields (observed on safety-filtered
        # responses where `candidates_token_count` is set to None rather
        # than 0). Downstream `estimate_cost_usd` does `tokens / 1_000_000`
        # which raises `unsupported operand type(s) for /: 'NoneType' and
        # 'int'`. The `or 0` coerces None and missing both to 0 — a
        # safety-filtered call legitimately produced zero output tokens.
        in_tok = int(getattr(usage, "prompt_token_count", 0) or 0) if usage else 0
        out_tok = int(getattr(usage, "candidates_token_count", 0) or 0) if usage else 0
        return ProviderCallResult(text=text, raw=resp, input_tokens=in_tok, output_tokens=out_tok)

    def retryable_exceptions(self) -> tuple[type[BaseException], ...]:
        # ProviderError covers transient SDK errors we wrapped above; the
        # other classes catch network-layer failures the SDK surfaces raw.
        return (TimeoutError, ConnectionError, OSError, ProviderError)


register_provider("gemini", GeminiProvider)
