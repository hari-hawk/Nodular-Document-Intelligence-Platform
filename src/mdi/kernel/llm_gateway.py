"""LLM Gateway.

Every LLM call in the codebase goes through this module. Direct provider
SDK imports anywhere else should fail review.

Responsibilities:
  * Provider abstraction (Gemini, Anthropic — extensible) via providers/
  * Tier-based routing (perception/extraction/reasoning/synthesis) via provider_router
  * Multimodal (text + image bytes)
  * Retry with exponential backoff via tenacity
  * Per-call timeout (default 120s)
  * CostTracker — daily global cap + per-tenant monthly ceiling
  * Optional Langfuse trace (no-op when keys absent)

Test strategy:
  Tests inject FakeGateway by passing it explicitly to organs, OR by
  monkeypatching the `_gateway_singleton` factory. Real provider calls
  are only exercised by the opt-in eval harness (`pytest -m live_llm`).
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from mdi.kernel.observability import get_langfuse, get_logger
from mdi.kernel.provider_router import OrganTier, route_chain
from mdi.kernel.providers import (
    BaseProvider,
    ProviderError,
    ProviderNotConfigured,
    get_provider,
)
from mdi.kernel.settings import get_settings
from mdi.models.schemas import LLMCall

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Cost tracking
# ---------------------------------------------------------------------------
class BudgetExceeded(RuntimeError):
    """Raised before a call fires when a cost ceiling would be breached."""


# Static price table (USD per 1M tokens). These are conservative; production
# should pull live from a price config that ops can update without a deploy.
PRICE_TABLE: dict[str, dict[str, float]] = {
    # Gemini
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
    "gemini-2.5-pro":   {"input": 1.25, "output": 10.00},
    # Anthropic — order-of-magnitude correct; keep updated.
    "claude-haiku-4-5":  {"input": 1.00, "output": 5.00},
    "claude-sonnet-4-5": {"input": 3.00, "output": 15.00},
    "claude-opus-4-1":   {"input": 15.00, "output": 75.00},
}


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    p = PRICE_TABLE.get(model)
    if p is None:
        return 0.0
    return (input_tokens / 1_000_000) * p["input"] + (output_tokens / 1_000_000) * p["output"]


@dataclass
class CostTracker:
    """In-memory daily aggregator. Persistent per-tenant ceiling check
    happens against the `cost_events` table — see `check_tenant_ceiling`."""

    daily_cap_usd: float
    soft_warn_pct: float = 0.80
    hard_cap_pct: float = 1.00
    _today: date = field(default_factory=date.today)
    _spent_today_usd: float = 0.0
    _events: list[LLMCall] = field(default_factory=list)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def precheck(self, projected_cost_usd: float) -> None:
        async with self._lock:
            if date.today() != self._today:
                self._today = date.today()
                self._spent_today_usd = 0.0
                self._events.clear()
            cap = self.daily_cap_usd * self.hard_cap_pct
            if self._spent_today_usd + projected_cost_usd > cap:
                raise BudgetExceeded(
                    f"daily cap {cap:.4f} USD would be exceeded "
                    f"(spent={self._spent_today_usd:.4f}, projected={projected_cost_usd:.4f})"
                )
            warn = self.daily_cap_usd * self.soft_warn_pct
            if self._spent_today_usd + projected_cost_usd > warn:
                logger.warning(
                    "cost.soft_warn",
                    spent_usd=self._spent_today_usd,
                    projected_usd=projected_cost_usd,
                    cap_usd=self.daily_cap_usd,
                )

    async def record(self, call: LLMCall) -> None:
        async with self._lock:
            self._spent_today_usd += call.cost_usd
            self._events.append(call)

    @property
    def spent_today_usd(self) -> float:
        return self._spent_today_usd

    @property
    def events(self) -> list[LLMCall]:
        return list(self._events)


# ---------------------------------------------------------------------------
# Gateway protocol — what every organ depends on
# ---------------------------------------------------------------------------
class GatewayLike(Protocol):
    async def generate(
        self,
        *,
        organ: str,
        prompt: str,
        system: str | None = ...,
        images: list[bytes] | None = ...,
        json_mode: bool = ...,
        tenant_id: uuid.UUID | None = ...,
        max_output_tokens: int | None = ...,
        temperature: float = ...,
        # Either an explicit (provider, model) OR a tier — exactly one.
        model: str | None = ...,
        provider: str | None = ...,
        tier: OrganTier | None = ...,
    ) -> GatewayResponse: ...


@dataclass
class GatewayResponse:
    text: str
    raw: Any
    call: LLMCall


# ---------------------------------------------------------------------------
# Real gateway — delegates to the provider registry
# ---------------------------------------------------------------------------
class LLMGateway:
    """The production gateway. One instance per process; tests inject FakeGateway."""

    def __init__(self, *, cost_tracker: CostTracker | None = None) -> None:
        s = get_settings()
        self.cost_tracker = cost_tracker or CostTracker(
            daily_cap_usd=s.daily_spend_cap_usd,
            soft_warn_pct=s.cost_soft_warn_pct,
            hard_cap_pct=s.cost_hard_cap_pct,
        )
        self.timeout = s.llm_timeout_seconds
        self.max_retries = s.llm_max_retries
        self._lf = get_langfuse()

    def _resolve_chain(
        self,
        *,
        provider: str | None,
        model: str | None,
        tier: OrganTier | None,
    ) -> list[tuple[str, str]]:
        """Pick the candidate chain for this call.

        - tier=  → full router chain (primary + fallbacks)
        - explicit provider+model → single-element chain (no fallback)
        """
        if tier is not None and provider is None and model is None:
            return route_chain(tier)
        if provider is not None and model is not None:
            return [(provider, model)]
        raise ValueError(
            "generate() needs either a `tier=` OR an explicit `provider=`+`model=` pair"
        )

    async def _call_one(
        self,
        prov: BaseProvider,
        chosen_model: str,
        *,
        prompt: str,
        system: str | None,
        images: list[bytes],
        json_mode: bool,
        max_output_tokens: int | None,
        temperature: float,
    ) -> Any:
        """Single-provider call with retry. Returns the ProviderCallResult."""
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(multiplier=2, min=2, max=30),
            retry=retry_if_exception_type(prov.retryable_exceptions()),
            reraise=True,
        ):
            with attempt:
                return await asyncio.wait_for(
                    prov.call(
                        model=chosen_model,
                        prompt=prompt,
                        system=system,
                        images=images,
                        json_mode=json_mode,
                        max_output_tokens=max_output_tokens,
                        temperature=temperature,
                    ),
                    timeout=self.timeout,
                )
        # AsyncRetrying with reraise=True covers all paths — this is unreachable
        # but keeps the type checker happy.
        raise RuntimeError("retry loop exited without result")  # pragma: no cover

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
        model: str | None = None,
        provider: str | None = None,
        tier: OrganTier | None = None,
    ) -> GatewayResponse:
        chain = self._resolve_chain(provider=provider, model=model, tier=tier)
        request_id = str(uuid.uuid4())

        # Pre-check using the cheapest candidate's price (fail fast on budget).
        approx_input = (len(prompt) + len(system or "")) // 4
        approx_output = max_output_tokens or 1024
        cheapest = min(
            (estimate_cost_usd(m, approx_input, approx_output) for _p, m in chain),
            default=0.0,
        )
        await self.cost_tracker.precheck(cheapest)

        last_exc: BaseException | None = None
        for idx, (prov_name, chosen_model) in enumerate(chain):
            prov = get_provider(prov_name)
            trace = self._lf.trace(
                name=f"llm:{organ}",
                metadata={
                    "request_id": request_id,
                    "provider": prov.name,
                    "model": chosen_model,
                    "fallback_index": idx,
                    "tenant_id": str(tenant_id) if tenant_id else None,
                },
            )
            started = time.monotonic()
            try:
                result = await self._call_one(
                    prov, chosen_model,
                    prompt=prompt,
                    system=system,
                    images=images or [],
                    json_mode=json_mode,
                    max_output_tokens=max_output_tokens,
                    temperature=temperature,
                )
            except (ProviderNotConfigured, RetryError) as e:
                last_exc = e
                trace.end(level="WARNING", status_message=f"fallback: {type(e).__name__}")
                logger.warning(
                    "llm.fallback",
                    organ=organ,
                    failed_provider=prov.name,
                    failed_model=chosen_model,
                    request_id=request_id,
                    reason=str(e)[:200],
                    next_in_chain=chain[idx + 1] if idx + 1 < len(chain) else None,
                )
                continue
            except ProviderError as e:
                # Non-retryable provider-level error (auth, schema). Don't
                # cascade — the same input is unlikely to succeed elsewhere.
                trace.end(level="ERROR", status_message=str(e))
                raise
            finally:
                elapsed = time.monotonic() - started
                logger.info(
                    "llm.call",
                    organ=organ,
                    provider=prov.name,
                    model=chosen_model,
                    request_id=request_id,
                    fallback_index=idx,
                    elapsed_s=round(elapsed, 3),
                )

            # Success path
            cost = estimate_cost_usd(chosen_model, result.input_tokens, result.output_tokens)
            call = LLMCall(
                organ=organ,
                model=chosen_model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                cost_usd=cost,
                request_id=request_id,
            )
            await self.cost_tracker.record(call)
            trace.end(metadata={
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "cost_usd": cost,
                "fallback_index": idx,
            })
            return GatewayResponse(text=result.text, raw=result.raw, call=call)

        # All chain candidates exhausted — re-raise the last failure.
        assert last_exc is not None
        raise last_exc


# ---------------------------------------------------------------------------
# Singleton + factory used by organs
# ---------------------------------------------------------------------------
_gateway_singleton: GatewayLike | None = None


def get_gateway() -> GatewayLike:
    """Return the process-wide gateway. Tests can override by setting the
    module-level `_gateway_singleton` to a FakeGateway instance."""
    global _gateway_singleton
    if _gateway_singleton is None:
        _gateway_singleton = LLMGateway()
    return _gateway_singleton


def set_gateway(gw: GatewayLike) -> None:
    """Override the singleton — for tests."""
    global _gateway_singleton
    _gateway_singleton = gw


def reset_gateway() -> None:
    """Drop the singleton — next get_gateway() will rebuild."""
    global _gateway_singleton
    _gateway_singleton = None


# Re-export ProviderError for callers that want to differentiate.
__all__ = [
    "PRICE_TABLE",
    "BudgetExceeded",
    "CostTracker",
    "GatewayLike",
    "GatewayResponse",
    "LLMGateway",
    "ProviderError",
    "estimate_cost_usd",
    "get_gateway",
    "reset_gateway",
    "set_gateway",
]
