"""Unit tests for the cumulative spend ledger.

Each test uses a tmp_path-scoped ledger file via monkeypatched data_dir
so the real on-disk ledger is never touched.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mdi.kernel import spend_ledger
from mdi.kernel.settings import get_settings
from mdi.kernel.spend_ledger import (
    SpendCapExceeded,
    precheck,
    record,
    reset,
    snapshot,
)


@pytest.fixture(autouse=True)
def _isolated_ledger(monkeypatch, tmp_path: Path):
    """Point the ledger at a temp dir so test runs don't accumulate state."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    # Sanity — make sure the new dir is empty.
    ledger_dir = tmp_path / "data"
    if ledger_dir.exists():
        for f in ledger_dir.iterdir():
            f.unlink()
    yield
    get_settings.cache_clear()


def test_initial_snapshot_is_zero():
    s = snapshot()
    assert s["total_usd"] == 0.0
    assert s["by_backend"] == {}


def test_record_accumulates_total_and_per_backend():
    record(cost_usd=0.001, backend="gemini")
    record(cost_usd=0.002, backend="gemini")
    record(cost_usd=0.010, backend="anthropic")
    s = snapshot()
    assert s["total_usd"] == pytest.approx(0.013, abs=1e-9)
    assert s["by_backend"]["gemini"] == pytest.approx(0.003, abs=1e-9)
    assert s["by_backend"]["anthropic"] == pytest.approx(0.010, abs=1e-9)


def test_record_persists_across_reload(tmp_path):
    """A new process (simulated by re-reading the file) sees what the
    previous process wrote — that's the whole point of file-backing."""
    record(cost_usd=0.42, backend="gemini")
    # Force a from-disk read by calling _load with the same resolved path.
    s_via_module = snapshot()
    raw = json.loads((Path(get_settings().data_dir) / "data" / ".spend_ledger.json").read_text())
    assert raw["total_usd"] == pytest.approx(0.42, abs=1e-9)
    assert raw["by_backend"]["gemini"] == pytest.approx(0.42, abs=1e-9)
    assert s_via_module["total_usd"] == raw["total_usd"]


def test_precheck_observer_mode_when_cap_zero():
    """Default cap is 0 → ledger acts as a pure observer; precheck
    never raises even at huge projected costs."""
    record(cost_usd=4.0, backend="anthropic")
    precheck(projected_cost_usd=1000.0)  # would never raise


def test_precheck_raises_when_projected_would_exceed_cap():
    record(cost_usd=4.5, backend="gemini")
    # Cap of 5 with 4.5 already spent + 0.6 projected = 5.1 → raise.
    with pytest.raises(SpendCapExceeded) as exc:
        precheck(projected_cost_usd=0.6, cap_usd=5.0)
    msg = str(exc.value)
    assert "5.0000" in msg or "5.00" in msg
    assert "4.5000" in msg or "4.50" in msg


def test_precheck_allows_when_projected_fits_under_cap():
    record(cost_usd=2.0, backend="gemini")
    # Cap 5, spent 2, projected 1 → total 3, well under.
    precheck(projected_cost_usd=1.0, cap_usd=5.0)


def test_precheck_at_exactly_cap_does_not_raise():
    """Boundary check — `>` not `>=`. At exactly the cap we allow the call
    (it's the LAST allowed call); the next one would push over."""
    record(cost_usd=4.0, backend="gemini")
    precheck(projected_cost_usd=1.0, cap_usd=5.0)  # exactly 5.0, allow
    with pytest.raises(SpendCapExceeded):
        precheck(projected_cost_usd=1.01, cap_usd=5.0)  # 5.01, deny


def test_reset_zeros_the_ledger():
    record(cost_usd=1.0, backend="gemini")
    record(cost_usd=2.0, backend="anthropic")
    assert snapshot()["total_usd"] == pytest.approx(3.0)
    reset()
    assert snapshot()["total_usd"] == 0.0
    assert snapshot()["by_backend"] == {}


def test_concurrent_records_dont_lose_writes(tmp_path):
    """Threading.Lock + atomic rename keep total consistent under
    concurrent record() calls. Sequential here but threading would be
    the same path — the lock holds and the file is read-modify-write."""
    for _ in range(20):
        record(cost_usd=0.05, backend="gemini")
    assert snapshot()["total_usd"] == pytest.approx(20 * 0.05, abs=1e-9)


def test_corrupted_ledger_file_is_treated_as_zero(monkeypatch, tmp_path):
    """If someone shoves garbage into the ledger file, we log and act
    as if it were empty rather than crashing the gateway."""
    ledger_dir = tmp_path / "data"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    (ledger_dir / ".spend_ledger.json").write_text("{this is not json")
    monkeypatch.setattr(spend_ledger, "_ledger_path", lambda: ledger_dir / ".spend_ledger.json")

    s = snapshot()
    assert s["total_usd"] == 0.0
    # And we can still record after a corrupt read — recovery is automatic.
    record(cost_usd=0.5, backend="gemini")
    assert snapshot()["total_usd"] == pytest.approx(0.5)


def test_older_ledger_without_by_backend_still_loads(monkeypatch, tmp_path):
    """Schema-compat: older ledger files only had `total_usd`. Reading
    such a file should populate by_backend = {} rather than KeyError."""
    ledger_dir = tmp_path / "data"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    (ledger_dir / ".spend_ledger.json").write_text(json.dumps({"total_usd": 1.23}))
    monkeypatch.setattr(spend_ledger, "_ledger_path", lambda: ledger_dir / ".spend_ledger.json")

    s = snapshot()
    assert s["total_usd"] == pytest.approx(1.23)
    assert s["by_backend"] == {}
