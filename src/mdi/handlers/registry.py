"""Handler registry — the allow-list of vetted Python callables that
patterns, findings, and natural-language commands can invoke.

Contract for a handler:
  async def my_handler(ctx: HandlerContext) -> HandlerResult

Inputs (HandlerContext):
  - tenant_id: which tenant we're acting on (RLS scope is set by caller)
  - document_id: which document (optional — handlers may be batch-scoped)
  - extraction: the Extraction dict (canonical names, post-normalisation)
  - kwargs: free-form arguments from the caller (the LLM-via-tool-use
    or the analyst-via-UI passes these)

Outputs (HandlerResult):
  - ok: did the handler complete?
  - output: human-readable summary (shown in the UI)
  - data: any structured side data (downstream consumers can act on it)
  - side_effects: a list of actions the handler took (so audit logs
    can record what the LLM dispatched)

Handlers are registered via @register("handler_id", description=...).
Discovery happens at module import — see mdi/handlers/__init__.py for
how builtins force-import so they self-register.
"""
from __future__ import annotations

import inspect
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from mdi.kernel.observability import get_logger

logger = get_logger(__name__)


@dataclass
class HandlerContext:
    tenant_id: uuid.UUID
    document_id: uuid.UUID | None = None
    extraction: dict[str, Any] = field(default_factory=dict)
    cluster: dict[str, Any] = field(default_factory=dict)
    kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass
class HandlerResult:
    ok: bool
    output: str
    data: dict[str, Any] = field(default_factory=dict)
    side_effects: list[str] = field(default_factory=list)


@dataclass
class _Registration:
    handler_id: str
    func: Callable[[HandlerContext], Awaitable[HandlerResult]]
    description: str
    # Human-friendly signature shown in the admin UI and used by the
    # LLM dispatcher prompt: "tell me when to invoke each handler".
    when_to_use: str


_REGISTRY: dict[str, _Registration] = {}


def register(
    handler_id: str,
    *,
    description: str = "",
    when_to_use: str = "",
) -> Callable:
    """Decorator. Adds the handler to the registry.

    Raises at import time if `handler_id` is already taken — handler ids
    are the public contract and silent collisions would let one
    pack's update mask another pack's handler.
    """
    def decorate(func: Callable[[HandlerContext], Awaitable[HandlerResult]]):
        if handler_id in _REGISTRY:
            existing = _REGISTRY[handler_id]
            raise ValueError(
                f"handler_id={handler_id!r} already registered by "
                f"{existing.func.__module__}.{existing.func.__name__}"
            )
        if not inspect.iscoroutinefunction(func):
            raise TypeError(
                f"handler {handler_id!r} must be `async def` — got "
                f"{type(func).__name__}"
            )
        _REGISTRY[handler_id] = _Registration(
            handler_id=handler_id,
            func=func,
            description=description,
            when_to_use=when_to_use,
        )
        return func
    return decorate


def list_handlers() -> list[dict[str, str]]:
    """Public manifest of registered handlers — used by the
    /admin/handlers endpoint and as the system prompt seed for the
    LLM dispatcher."""
    return sorted(
        (
            {
                "handler_id": r.handler_id,
                "description": r.description,
                "when_to_use": r.when_to_use,
            }
            for r in _REGISTRY.values()
        ),
        key=lambda d: d["handler_id"],
    )


async def run_handler(handler_id: str, ctx: HandlerContext) -> HandlerResult:
    """Look up `handler_id` in the registry and execute it. Surfaces a
    structured error result (NOT a raised exception) when:
      - handler is unknown
      - handler raised mid-execution
    so the caller can audit + display the failure without crashing the
    request."""
    reg = _REGISTRY.get(handler_id)
    if reg is None:
        return HandlerResult(
            ok=False,
            output=f"unknown handler_id: {handler_id!r}",
            data={"known_ids": [r.handler_id for r in _REGISTRY.values()]},
        )
    try:
        result = await reg.func(ctx)
    except Exception as exc:
        logger.warning(
            "handler.execution_failed",
            handler_id=handler_id,
            error=str(exc),
        )
        return HandlerResult(
            ok=False,
            output=f"handler raised: {exc}",
            data={"exception_type": type(exc).__name__},
        )
    return result


def reset_registry() -> None:
    """Test helper — drop all registered handlers. Production code
    should never call this. Repopulating requires re-importing the
    modules that defined the handlers."""
    _REGISTRY.clear()
