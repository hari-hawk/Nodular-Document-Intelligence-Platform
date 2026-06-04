"""Google Gemini adapter.

Lazy-imports `google.generativeai` so test environments without the
package can still load this module.
"""
from __future__ import annotations

import asyncio
from typing import Any

from mdi.kernel.providers.base import (
    BaseProvider,
    ProviderCallResult,
    ProviderNotConfigured,
    register_provider,
)
from mdi.kernel.settings import get_settings


class GeminiProvider(BaseProvider):
    name = "gemini"
    supports_vision = True
    supports_json_mode = True
    supports_tools = True

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
        s = get_settings()
        if not s.google_api_key:
            raise ProviderNotConfigured(
                "GOOGLE_API_KEY is empty. Either set it or inject a FakeGateway in tests."
            )
        import google.generativeai as genai  # type: ignore[import-not-found]
        genai.configure(api_key=s.google_api_key)

        client = genai.GenerativeModel(
            model_name=model,
            system_instruction=system,
            generation_config={
                "temperature": temperature,
                "max_output_tokens": max_output_tokens or 4096,
                "response_mime_type": "application/json" if json_mode else "text/plain",
            },
        )

        parts: list[Any] = [prompt]
        for blob in images:
            parts.append({"mime_type": "image/png", "data": blob})

        resp = await asyncio.to_thread(client.generate_content, parts)
        text = getattr(resp, "text", "") or ""
        usage = getattr(resp, "usage_metadata", None)
        in_tok = getattr(usage, "prompt_token_count", 0) if usage else 0
        out_tok = getattr(usage, "candidates_token_count", 0) if usage else 0
        return ProviderCallResult(text=text, raw=resp, input_tokens=in_tok, output_tokens=out_tok)

    def retryable_exceptions(self) -> tuple[type[BaseException], ...]:
        return (TimeoutError, ConnectionError, OSError)


register_provider("gemini", GeminiProvider)
