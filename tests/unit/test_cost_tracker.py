"""CostTracker — daily cap + budget exceeded behaviour."""
from __future__ import annotations

import pytest

from mdi.kernel.llm_gateway import BudgetExceeded, CostTracker, estimate_cost_usd
from mdi.models.schemas import LLMCall


@pytest.mark.asyncio
async def test_cost_tracker_records_under_cap():
    t = CostTracker(daily_cap_usd=1.00)
    await t.precheck(0.05)
    await t.record(LLMCall(organ="x", model="gemini-2.5-flash", input_tokens=100, output_tokens=200, cost_usd=0.05))
    assert t.spent_today_usd == 0.05


@pytest.mark.asyncio
async def test_cost_tracker_blocks_at_cap():
    t = CostTracker(daily_cap_usd=0.10)
    await t.record(LLMCall(organ="x", model="gemini-2.5-flash", input_tokens=100, output_tokens=200, cost_usd=0.09))
    with pytest.raises(BudgetExceeded):
        await t.precheck(0.05)


def test_estimate_cost_known_model():
    cost = estimate_cost_usd("gemini-2.5-flash", 1_000_000, 1_000_000)
    # 0.30 + 2.50 = 2.80 USD per 1M+1M tokens
    assert pytest.approx(cost, rel=1e-6) == 2.80


def test_estimate_cost_unknown_model_returns_zero():
    assert estimate_cost_usd("bogus-model", 1_000_000, 1_000_000) == 0.0
