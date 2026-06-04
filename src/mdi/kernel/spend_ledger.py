"""Cumulative spend ledger — file-backed cap surviving process restarts.

MDI already has CostTracker (llm_gateway.py): in-memory, per-process,
daily-window aggregator with a soft-warn + hard-daily-cap. That's the
right tool for "this batch is about to blow the day's budget". It's the
WRONG tool for two adjacent questions:

  1. "What did this deployment spend in total across restarts?"
  2. "Did we hit our hard cumulative ceiling, not just the daily one?"

Digital-Direction answers both with a file-backed atomic counter that
persists across worker restarts and is re-loaded on every write so two
processes sharing the same data_dir stay consistent. This module ports
the pattern.

Design:
  - JSON file at `<data_dir>/.spend_ledger.json`
  - Re-read on every operation to stay multi-process consistent.
    (`threading.Lock` is in-process; the disk re-read covers
    cross-process. DD's empirical workload of <100 LLM calls per
    minute per worker means the lock-then-fsync cost is invisible.)
  - Per-backend tallies (gemini, anthropic, vertex) so cost reports
    can break down spend by provider — the kind of question that comes
    up immediately after the first invoice from Anthropic lands.
  - `SpendCapExceeded` raised on precheck when the cumulative cap is
    set and a pending call would push us over.
  - When `cumulative_spend_cap_usd == 0` the ceiling is disabled and
    the ledger acts as a pure observer — record() still writes, but
    precheck() never raises. Default is 0 so this commit is purely
    additive.

Not a replacement for CostTracker — both gate LLM calls. CostTracker
covers the day; SpendLedger covers forever.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from mdi.kernel.observability import get_logger
from mdi.kernel.settings import get_settings

logger = get_logger(__name__)


class SpendCapExceeded(RuntimeError):
    """Raised when a pending LLM call would push cumulative spend past
    the configured cumulative cap. Distinct from `BudgetExceeded` (which
    is CostTracker's daily-cap signal) so callers can distinguish."""


_LOCK = threading.Lock()


def _ledger_path() -> Path:
    """Resolve at call time so tests can monkey-patch `data_dir`."""
    s = get_settings()
    data_dir = Path(getattr(s, "data_dir", None) or ".") / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / ".spend_ledger.json"


def _load(path: Path | None = None) -> dict[str, Any]:
    """Read the ledger from disk. Returns the canonical default shape
    when the file doesn't exist or is unreadable — never raises, because
    we'd rather under-report spend than crash a hot LLM call path on a
    transient FS hiccup."""
    p = path or _ledger_path()
    if not p.exists():
        return {"total_usd": 0.0, "by_backend": {}}
    try:
        data = json.loads(p.read_text())
        # Older ledgers may only have total_usd — fill in by_backend.
        data.setdefault("by_backend", {})
        data.setdefault("total_usd", 0.0)
        return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("spend_ledger.load_failed", path=str(p), error=str(exc))
        return {"total_usd": 0.0, "by_backend": {}}


def _save(data: dict[str, Any], path: Path | None = None) -> None:
    """Atomic write via temp + rename. The temp file lives next to the
    target so the rename is atomic on POSIX (same filesystem). Never
    raises — failure to persist just means the next process starts
    counting from whatever did get persisted."""
    p = path or _ledger_path()
    tmp = p.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(p)
    except OSError as exc:
        logger.warning("spend_ledger.save_failed", path=str(p), error=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# Public API — both async-safe (threading.Lock is fine in async too because
# the holds are microseconds and never await anything).
# ─────────────────────────────────────────────────────────────────────────────
def precheck(projected_cost_usd: float, *, cap_usd: float | None = None) -> None:
    """Raise SpendCapExceeded if `projected_cost_usd` would push the
    cumulative ledger past the configured cap. Pass `cap_usd` explicitly
    to override the settings value (tests + scripts use this)."""
    if cap_usd is None:
        s = get_settings()
        cap_usd = getattr(s, "cumulative_spend_cap_usd", 0.0)
    if not cap_usd or cap_usd <= 0:
        return  # cap disabled — observer mode

    with _LOCK:
        data = _load()
        spent = float(data.get("total_usd") or 0.0)
        if spent + projected_cost_usd > cap_usd:
            raise SpendCapExceeded(
                f"cumulative cap {cap_usd:.4f} USD would be exceeded "
                f"(spent_so_far={spent:.4f}, projected={projected_cost_usd:.4f})"
            )


def record(*, cost_usd: float, backend: str) -> dict[str, float]:
    """Append `cost_usd` to the ledger, broken out by backend. Returns
    the post-record state — useful for callers that want to log the new
    cumulative total without re-reading the file."""
    with _LOCK:
        data = _load()
        data["total_usd"] = float(data.get("total_usd") or 0.0) + float(cost_usd)
        by = data.setdefault("by_backend", {})
        by[backend] = float(by.get(backend, 0.0)) + float(cost_usd)
        _save(data)
        return {
            "total_usd": data["total_usd"],
            **{f"by_backend.{k}": v for k, v in by.items()},
        }


def snapshot() -> dict[str, Any]:
    """Read-only view of the current ledger state — used by the
    /admin/spend endpoint and the Streamlit cost panel."""
    with _LOCK:
        return _load()


def reset() -> None:
    """Test helper / dev-loop only. Truncates the ledger file. NEVER
    expose via an API — accidentally calling this in production would
    silently zero out the audit trail."""
    with _LOCK:
        _save({"total_usd": 0.0, "by_backend": {}})
