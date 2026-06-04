"""Code-bridge: registered Python handlers that patterns + commands can invoke.

The platform learns patterns from documents and stores them in
Hippocampus. Some patterns are useful by themselves (a Schema, a
RuleSet). Others would benefit from running specific deterministic
LOGIC when matched — e.g. "Verizon invoices need their tax-rate
normalised before downstream consumers see them."

The code-bridge lets a pattern (or a Conscience finding, or a chat
command from the analyst) carry a `handler_id` string that maps to a
vetted Python callable in `mdi.handlers`. The platform looks up the
handler in the registry and runs it with the document context.

Why a registry, not eval-from-YAML:
  - simpleeval (Conscience's rule engine) is intentionally limited.
    Real validation logic often needs imports, control flow, and
    library calls that simpleeval can't safely allow.
  - A registry of vetted handlers keeps the safety boundary clear:
    new handlers are CODE CHANGES reviewed in PR, not config.
  - The LLM's role is DISPATCHER (pick which handler), not executor
    (run arbitrary code). Allow-list is the safety layer.

Two builtin handlers ship in this commit (recompute_total,
flag_for_review). Pack authors can extend the registry by importing
mdi.handlers.registry.register at pack-load time.
"""
from __future__ import annotations

from mdi.handlers import builtins as _builtins  # registers on import
from mdi.handlers.registry import (
    HandlerContext,
    HandlerResult,
    list_handlers,
    register,
    run_handler,
)

# Force-import builtins so they self-register when mdi.handlers is first
# imported. Without this the registry would be empty until someone
# imported builtins directly.
_ = _builtins

__all__ = [
    "HandlerContext",
    "HandlerResult",
    "list_handlers",
    "register",
    "run_handler",
]
