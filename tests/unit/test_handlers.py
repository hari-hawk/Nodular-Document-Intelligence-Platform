"""Unit tests for the code-bridge handler registry (Wave 2.5)."""
from __future__ import annotations

import uuid

import pytest

from mdi.handlers import (
    HandlerContext,
    HandlerResult,
    list_handlers,
    register,
    run_handler,
)
from mdi.handlers.registry import reset_registry


# ─────────────────────────────────────────────────────────────────────────────
# Registry mechanics — using a custom in-test handler so the test isn't
# coupled to whichever builtin handlers happen to be registered.
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def isolated_registry():
    """Snapshot the registry, run the test on an empty one, restore.

    Importing this fixture also reinstalls the builtin handlers so the
    rest of the test session keeps working.
    """
    from mdi.handlers.registry import _REGISTRY
    snapshot = dict(_REGISTRY)
    reset_registry()
    yield
    reset_registry()
    _REGISTRY.update(snapshot)


@pytest.mark.asyncio
async def test_register_then_run(isolated_registry):
    @register("greet", description="say hello", when_to_use="for testing")
    async def _greet(ctx: HandlerContext) -> HandlerResult:
        return HandlerResult(ok=True, output=f"hi from {ctx.tenant_id}")

    ctx = HandlerContext(tenant_id=uuid.uuid4())
    result = await run_handler("greet", ctx)
    assert result.ok
    assert "hi from" in result.output


@pytest.mark.asyncio
async def test_unknown_handler_returns_structured_error(isolated_registry):
    """Asking for an id that isn't registered must return a HandlerResult
    (NOT raise) so the caller can audit the misroute without a 500."""
    result = await run_handler("does_not_exist", HandlerContext(tenant_id=uuid.uuid4()))
    assert result.ok is False
    assert "unknown handler_id" in result.output


@pytest.mark.asyncio
async def test_handler_exception_caught(isolated_registry):
    @register("boom")
    async def _boom(ctx: HandlerContext) -> HandlerResult:
        raise ValueError("kaboom")

    result = await run_handler("boom", HandlerContext(tenant_id=uuid.uuid4()))
    assert result.ok is False
    assert "kaboom" in result.output
    assert result.data["exception_type"] == "ValueError"


def test_duplicate_handler_id_raises_at_register_time(isolated_registry):
    @register("dup")
    async def _a(ctx):
        return HandlerResult(ok=True, output="")
    with pytest.raises(ValueError, match="already registered"):
        @register("dup")
        async def _b(ctx):
            return HandlerResult(ok=True, output="")


def test_sync_handler_rejected(isolated_registry):
    """The dispatcher always awaits — sync handlers would silently
    return coroutine objects. Catch the mistake at registration."""
    with pytest.raises(TypeError, match="async def"):
        @register("sync_bad")
        def _sync(ctx):
            return HandlerResult(ok=True, output="")


def test_list_handlers_returns_manifest():
    """Builtins should appear in the public manifest at import time."""
    manifest = list_handlers()
    ids = {h["handler_id"] for h in manifest}
    assert "recompute_total" in ids
    assert "flag_for_review" in ids
    # Sanity on the shape — the LLM dispatcher will read these fields.
    for h in manifest:
        assert "description" in h
        assert "when_to_use" in h


# ─────────────────────────────────────────────────────────────────────────────
# Builtin: recompute_total
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_recompute_total_matches():
    """Items sum to the printed total → matches=True."""
    extraction = {
        "total": {"value": 150.00, "confidence": 0.9},
        "line_items": {"value": [
            {"amount": 100.00},
            {"amount": 50.00},
        ], "confidence": 0.9},
    }
    ctx = HandlerContext(tenant_id=uuid.uuid4(), extraction=extraction)
    result = await run_handler("recompute_total", ctx)
    assert result.ok
    assert result.data["matches"] is True
    assert result.data["recomputed_total"] == 150.00


@pytest.mark.asyncio
async def test_recompute_total_mismatch():
    """Items sum to MORE than the printed total → matches=False."""
    extraction = {
        "total": {"value": 100.00, "confidence": 0.9},
        "line_items": {"value": [
            {"amount": 60.00},
            {"amount": 50.00},
        ], "confidence": 0.9},
    }
    ctx = HandlerContext(tenant_id=uuid.uuid4(), extraction=extraction)
    result = await run_handler("recompute_total", ctx)
    assert result.ok
    assert result.data["matches"] is False
    assert result.data["delta"] == 10.00  # 110 - 100


@pytest.mark.asyncio
async def test_recompute_total_uses_first_present_amount_key():
    """Some line items use `charge`, others `mrc_total`, others `amount`.
    The handler tries each in priority order and stops at the first hit."""
    extraction = {
        "total": {"value": 75.00, "confidence": 0.9},
        "line_items": {"value": [
            {"amount": 50.00},
            {"charge": 25.00},  # different key, still summed
        ], "confidence": 0.9},
    }
    result = await run_handler(
        "recompute_total",
        HandlerContext(tenant_id=uuid.uuid4(), extraction=extraction),
    )
    assert result.ok
    assert result.data["matches"] is True
    assert "amount" in result.data["amount_keys_used"]
    assert "charge" in result.data["amount_keys_used"]


@pytest.mark.asyncio
async def test_recompute_total_missing_inputs():
    """No `total`? Tell the caller — don't raise."""
    ctx = HandlerContext(tenant_id=uuid.uuid4(), extraction={})
    result = await run_handler("recompute_total", ctx)
    assert result.ok is False
    assert "no `total`" in result.output


# ─────────────────────────────────────────────────────────────────────────────
# Builtin: flag_for_review
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_flag_for_review_records_side_effect():
    doc_id = uuid.uuid4()
    ctx = HandlerContext(
        tenant_id=uuid.uuid4(),
        document_id=doc_id,
        kwargs={"reason": "suspected duplicate"},
    )
    result = await run_handler("flag_for_review", ctx)
    assert result.ok
    assert str(doc_id) in result.output
    assert "suspected duplicate" in result.output
    assert any("queue_review" in s for s in result.side_effects)


@pytest.mark.asyncio
async def test_flag_for_review_works_without_reason():
    ctx = HandlerContext(tenant_id=uuid.uuid4(), document_id=uuid.uuid4())
    result = await run_handler("flag_for_review", ctx)
    assert result.ok
    assert "no reason given" in result.output
