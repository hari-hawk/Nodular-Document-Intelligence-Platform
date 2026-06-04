"""Live-LLM test fixtures + opt-in gate.

These tests hit real Gemini (and optionally Claude). They cost a few
cents per run and need Postgres + Redis up. They are SKIPPED by default
unless the `--run-live` flag is passed on the pytest command line.

Run them:

    pytest --run-live -m live_llm tests/live_llm/

The marker `live_llm` is declared in pyproject.toml.
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

# Repo layout: tests/live_llm/conftest.py → repo root is two dirs up.
_ROOT = Path(__file__).resolve().parents[2]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# Load .env into the process environment if it exists. Live tests REQUIRE keys.
# We OVERWRITE here (not setdefault) because the offline conftest pins the key
# vars to empty strings to force tests offline by default.
_env = _ROOT / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            kk, vv = k.strip(), v.strip()
            if vv:
                os.environ[kk] = vv


SAMPLE_DOCS = _ROOT / "tests" / "fixtures" / "sample_docs"
TENANT_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
TENANT_B = uuid.UUID("22222222-2222-2222-2222-222222222222")


# ---------------------------------------------------------------------------
# Opt-in gate
# ---------------------------------------------------------------------------
def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-live",
        action="store_true",
        default=False,
        help="run live-LLM tests (costs a few cents per run, needs Postgres + Redis)",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item],
) -> None:
    if config.getoption("--run-live"):
        return
    skip_live = pytest.mark.skip(reason="need --run-live to opt into live LLM tests")
    for item in items:
        if "live_llm" in item.keywords:
            item.add_marker(skip_live)


# ---------------------------------------------------------------------------
# Pre-flight: verify Postgres + keys before running any live test.
# ---------------------------------------------------------------------------
def _postgres_reachable() -> bool:
    try:
        import psycopg

        with psycopg.connect(
            os.environ.get("DATABASE_URL_SYNC")
            or "postgresql://mdi:mdi@localhost:5532/mdi",
            connect_timeout=2,
        ):
            return True
    except Exception:
        return False


@pytest.fixture(scope="session", autouse=True)
def _live_preflight() -> None:
    """Skip the whole module if prerequisites aren't met."""
    if not os.environ.get("GOOGLE_API_KEY"):
        pytest.skip("GOOGLE_API_KEY not set", allow_module_level=True)
    if not _postgres_reachable():
        pytest.skip(
            "Postgres not reachable at localhost:5532 — run `docker-compose up -d` first",
            allow_module_level=True,
        )


# ---------------------------------------------------------------------------
# Fresh state + tenant bootstrap
# ---------------------------------------------------------------------------
def _admin_dsn() -> str:
    """Admin connection string (the `mdi` superuser, not the app role)."""
    return os.environ.get(
        "DATABASE_URL_ADMIN_SYNC", "postgresql://mdi:mdi@localhost:5532/mdi"
    )


@pytest.fixture
def fresh_db() -> None:
    """Truncate every tenant-scoped table and re-seed the two test tenants.

    Uses the superuser `mdi` so we can bypass RLS for the truncate; the
    app code (under `mdi_app`) is exercised after the truncate.
    """
    import psycopg

    with psycopg.connect(_admin_dsn(), autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SET row_security = off")
        cur.execute(
            "TRUNCATE documents, extractions, anomalies, patterns, corrections, "
            "audit_log, kg_nodes, kg_edges, batches, cost_events, doc_chunks "
            "RESTART IDENTITY CASCADE"
        )
        for tid, slug, name in [
            (str(TENANT_A), "tenant-a", "Tenant A (live test)"),
            (str(TENANT_B), "tenant-b", "Tenant B (live test)"),
        ]:
            cur.execute(
                "INSERT INTO tenants (id, slug, display_name, config) "
                "VALUES (%s, %s, %s, %s::jsonb) "
                "ON CONFLICT (id) DO UPDATE SET config = EXCLUDED.config",
                (tid, slug, name, "{}"),
            )


@pytest.fixture
def reset_runtime() -> None:
    """Drop all caches so each test gets a clean gateway/engine/provider chain."""
    from mdi.kernel.auth import reset_engine
    from mdi.kernel.llm_gateway import reset_gateway
    from mdi.kernel.providers.base import reset_providers
    from mdi.kernel.settings import get_settings

    get_settings.cache_clear()
    reset_providers()
    reset_gateway()
    reset_engine()


# ---------------------------------------------------------------------------
# Convenience: read sample docs
# ---------------------------------------------------------------------------
@pytest.fixture
def cross_industry_corpus() -> list[dict[str, object]]:
    files = [
        "telecom_invoice_att_001.txt",
        "healthcare_claim_837_001.txt",
        "cloud_finance_aws_001.txt",
        "legal_msa_001.txt",
    ]
    payloads = []
    for fn in files:
        path = SAMPLE_DOCS / fn
        if not path.exists():
            pytest.skip(f"sample doc missing: {fn}")
        payloads.append({"filename": fn, "content": path.read_bytes()})
    return payloads


@pytest.fixture
def att_invoice_3() -> dict[str, object]:
    p = SAMPLE_DOCS / "telecom_invoice_att_003.txt"
    if not p.exists():
        pytest.skip("telecom_invoice_att_003.txt missing")
    return {"filename": p.name, "content": p.read_bytes()}
