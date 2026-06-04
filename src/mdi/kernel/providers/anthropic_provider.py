"""Anthropic Claude adapter.

Use cases (per the routing policy):
  * Insight Cortex narration — Claude Sonnet excels at calibrated, grounded prose.
  * Chat synthesis layer — conversational quality, citation faithfulness.
  * Conscience invent (when enabled) — careful reasoning about validation rules.

Lazy-imports `anthropic` so test envs without the SDK can still load this module.

Note on JSON: unlike Gemini, Claude has no `response_mime_type=json` flag. We
ask for JSON in the system prompt AND defensively strip ```json``` fences
from the response when json_mode=True (Claude wraps JSON in fences anyway
~30% of the time despite explicit instructions).
"""
from __future__ import annotations

import base64
import re
from typing import Any

# Markdown code-fence stripper. Matches both ```json...``` and bare ```...```.
_FENCE_RE = re.compile(r"^\s*```(?:json|JSON)?\s*\n?(.*?)\n?```\s*$", re.DOTALL)


def _strip_fences(text: str) -> str:
    """Strip a single outer ```...``` fence if present, else return unchanged."""
    if not text:
        return text
    m = _FENCE_RE.match(text.strip())
    return m.group(1).strip() if m else text

from mdi.kernel.providers.base import (
    BaseProvider,
    ProviderCallResult,
    ProviderNotConfigured,
    register_provider,
)
from mdi.kernel.settings import get_settings


class AnthropicProvider(BaseProvider):
    name = "anthropic"
    supports_vision = True
    supports_json_mode = False  # Claude returns JSON via prompt, not a mime mode
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
        if not s.anthropic_api_key:
            raise ProviderNotConfigured(
                "ANTHROPIC_API_KEY is empty. Either set it or inject a FakeGateway in tests."
            )
        import anthropic  # type: ignore[import-not-found]
        client = anthropic.AsyncAnthropic(api_key=s.anthropic_api_key)

        # Build content blocks: optional images, then the prompt text.
        content_blocks: list[dict[str, Any]] = []
        for blob in images:
            content_blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": base64.b64encode(blob).decode("ascii"),
                    },
                }
            )

        # When json_mode is True we ask Claude (in the system prompt) to emit only JSON.
        effective_system = system or ""
        if json_mode:
            json_directive = (
                "\n\nReturn ONLY valid JSON. Do not include code fences, markdown, "
                "or any commentary."
            )
            effective_system = (effective_system + json_directive).strip()

        content_blocks.append({"type": "text", "text": prompt})

        message = await client.messages.create(
            model=model,
            max_tokens=max_output_tokens or 4096,
            temperature=temperature,
            system=effective_system or anthropic.NOT_GIVEN,
            messages=[{"role": "user", "content": content_blocks}],
        )

        # Concatenate text blocks (Claude can emit multiple).
        text_parts: list[str] = []
        for block in message.content:
            block_type = getattr(block, "type", None)
            if block_type == "text":
                text_parts.append(getattr(block, "text", ""))
        text = "".join(text_parts)

        # Defensive: strip ```json fences when caller asked for JSON, even if
        # we instructed Claude not to. Empirically Claude does it anyway.
        if json_mode:
            text = _strip_fences(text)

        usage = getattr(message, "usage", None)
        in_tok = getattr(usage, "input_tokens", 0) if usage else 0
        out_tok = getattr(usage, "output_tokens", 0) if usage else 0
        return ProviderCallResult(text=text, raw=message, input_tokens=in_tok, output_tokens=out_tok)

    def retryable_exceptions(self) -> tuple[type[BaseException], ...]:
        return (TimeoutError, ConnectionError, OSError)


register_provider("anthropic", AnthropicProvider)
