"""FakeGateway — replays canned LLM responses for offline test runs.

Match priority:
  1. Exact `(organ, model)` match on the next pending response in the queue.
  2. Wildcard `(organ, "*")` or `("*", "*")` from `defaults`.
  3. A built-in stub that returns shape-valid empty JSON.

Tests never need to touch real Gemini.
"""
from __future__ import annotations

import json
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from mdi.kernel.llm_gateway import (
    BudgetExceeded,
    CostTracker,
    GatewayResponse,
    estimate_cost_usd,
)
from mdi.models.schemas import LLMCall


@dataclass
class CannedResponse:
    organ: str
    model: str
    text: str
    input_tokens: int = 100
    output_tokens: int = 200


def _model_for_tier(tier: Any) -> str | None:
    """Best-effort tier -> default-model mapping for accounting in tests."""
    if tier is None:
        return None
    return {
        "perception": "gemini-2.5-flash",
        "extraction": "gemini-2.5-flash",
        "reasoning":  "gemini-2.5-pro",
        "synthesis":  "gemini-2.5-pro",
    }.get(str(tier), "gemini-2.5-flash")


def _shape_valid_default(organ: str) -> str:
    """Return JSON shaped like what each organ expects."""
    if organ == "eyes":
        return json.dumps(
            {
                "industry": "general_business",
                "vendor": "Acme Corp",
                "doc_type": "invoice",
                "layout": "free_text",
                "language": "en",
                "confidence": 0.85,
                "rationale": "test fixture",
            }
        )
    if organ == "pattern_cortex":
        return json.dumps(
            {
                "fields": [
                    {"name": "vendor", "type": "string", "required": True, "description": "Issuer"},
                    {"name": "customer", "type": "string", "required": False, "description": "Recipient"},
                    {"name": "document_number", "type": "string", "required": False, "description": "Number"},
                    {"name": "total", "type": "currency", "required": False, "description": "Total"},
                    {"name": "currency", "type": "string", "required": False, "description": "ISO 4217"},
                    {"name": "account_number", "type": "string", "required": False, "description": "Account"},
                ],
                "primary_keys": ["document_number"],
            }
        )
    if organ == "hands":
        return json.dumps(
            {
                "fields": {
                    "vendor": {"value": "Acme Corp", "confidence": 0.92, "source_text": "From: Acme Corp", "page": 1},
                    "customer": {"value": "Globex Inc.", "confidence": 0.88, "source_text": "Bill To: Globex Inc.", "page": 1},
                    "document_number": {"value": "INV-1001", "confidence": 0.95, "source_text": "Invoice Number: INV-1001", "page": 1},
                    "total": {"value": 1234.56, "confidence": 0.90, "source_text": "Total: 1234.56", "page": 1},
                    "currency": {"value": "USD", "confidence": 0.95, "source_text": "Currency: USD", "page": 1},
                    "account_number": {"value": "0133442501", "confidence": 0.85, "source_text": "Account: 133442501", "page": 1},
                }
            }
        )
    if organ == "conscience_invent":
        return json.dumps({"rules": []})
    if organ == "narrator":
        return "Processed 1 document. No high-severity findings; routine batch."
    if organ == "chat":
        return "Test answer from FakeGateway."
    return "{}"


@dataclass
class FakeGateway:
    """Drop-in replacement for GeminiGateway in tests."""

    queue: deque[CannedResponse] = field(default_factory=deque)
    defaults: dict[tuple[str, str], CannedResponse] = field(default_factory=dict)
    cost_tracker: CostTracker = field(default_factory=lambda: CostTracker(daily_cap_usd=100.0))
    raise_on_unknown: bool = False
    calls: list[LLMCall] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Test-side authoring helpers
    # ------------------------------------------------------------------
    def queue_response(self, organ: str, model: str, text: str, **kw: Any) -> None:
        self.queue.append(CannedResponse(organ=organ, model=model, text=text, **kw))

    def set_default(self, organ: str, model: str, text: str, **kw: Any) -> None:
        self.defaults[(organ, model)] = CannedResponse(organ=organ, model=model, text=text, **kw)

    # ------------------------------------------------------------------
    # GatewayLike protocol
    # ------------------------------------------------------------------
    async def generate(
        self,
        *,
        organ: str,
        prompt: str,
        system: str | None = None,
        images: list[bytes] | None = None,
        json_mode: bool = False,
        tenant_id: uuid.UUID | None = None,
        max_output_tokens: int | None = None,
        temperature: float = 0.1,
        # New unified-routing surface — one of (tier) or (provider+model).
        model: str | None = None,
        provider: str | None = None,
        tier: Any | None = None,
    ) -> GatewayResponse:
        # Resolve to a concrete model id for cost accounting + canned lookup.
        resolved_model = model or _model_for_tier(tier) or "gemini-2.5-flash"

        approx_input = (len(prompt) + len(system or "")) // 4
        approx_output = max_output_tokens or 256
        projected = estimate_cost_usd(resolved_model, approx_input, approx_output)
        try:
            await self.cost_tracker.precheck(projected)
        except BudgetExceeded:
            raise

        canned = self._next(organ, resolved_model)
        call = LLMCall(
            organ=organ,
            model=resolved_model,
            input_tokens=canned.input_tokens,
            output_tokens=canned.output_tokens,
            cost_usd=estimate_cost_usd(resolved_model, canned.input_tokens, canned.output_tokens),
            request_id=str(uuid.uuid4()),
        )
        await self.cost_tracker.record(call)
        self.calls.append(call)
        return GatewayResponse(text=canned.text, raw={"fake": True}, call=call)

    def _next(self, organ: str, model: str) -> CannedResponse:
        # Queued exact match wins.
        for i, r in enumerate(self.queue):
            if r.organ == organ and (r.model == model or r.model == "*"):
                del self.queue[i]
                return r
        # Defaults.
        for key in [(organ, model), (organ, "*"), ("*", "*")]:
            if key in self.defaults:
                return self.defaults[key]
        # Final fallback — built-in stub.
        if self.raise_on_unknown:
            raise AssertionError(f"FakeGateway: no canned response for organ={organ!r} model={model!r}")
        return CannedResponse(organ=organ, model=model, text=_shape_valid_default(organ))
