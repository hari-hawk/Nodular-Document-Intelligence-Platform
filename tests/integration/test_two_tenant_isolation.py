"""Two-tenant RLS isolation test.

Marked `integration` — needs Postgres + Redis (`docker compose up -d`)
plus `alembic upgrade head`. Skipped when DATABASE_URL is unreachable.

Verifies the Phase-1 exit criterion: two test tenants run in parallel
without seeing each other's data.
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest

pytestmark = [pytest.mark.integration]


def _db_reachable() -> bool:
    try:
        import psycopg

        psycopg.connect(
            os.environ.get("DATABASE_URL", "postgresql://mdi:mdi@localhost:5432/mdi"),
            connect_timeout=2,
        ).close()
        return True
    except Exception:
        return False


@pytest.mark.asyncio
@pytest.mark.skipif(not _db_reachable(), reason="Postgres not running locally")
async def test_two_tenants_are_isolated(installed_fake_gateway):
    from sqlalchemy import select

    from mdi.kernel.auth import reset_engine, tenant_session
    from mdi.models.db import Document
    from mdi.orchestrator.pipeline import run_batch_async

    reset_engine()

    # Bootstrap two tenants outside RLS context — uses admin connection via psycopg.
    import psycopg

    a = uuid.uuid4()
    b = uuid.uuid4()
    with psycopg.connect(
        os.environ.get("DATABASE_URL", "postgresql://mdi:mdi@localhost:5432/mdi"),
        autocommit=True,
    ) as conn, conn.cursor() as cur:
        cur.execute("SET row_security = off")
        cur.execute(
            "INSERT INTO tenants (id, slug, display_name) VALUES (%s, %s, %s)",
            (str(a), f"test-a-{a.hex[:6]}", "Tenant A"),
        )
        cur.execute(
            "INSERT INTO tenants (id, slug, display_name) VALUES (%s, %s, %s)",
            (str(b), f"test-b-{b.hex[:6]}", "Tenant B"),
        )

    # Run a batch as each tenant.
    payload = {"filename": "x.txt", "content": b"From: Acme Corp\nTotal: 10\n"}
    await asyncio.gather(
        run_batch_async(tenant_id=str(a), payloads=[payload], persist=True),
        run_batch_async(tenant_id=str(b), payloads=[payload], persist=True),
    )

    # As tenant A — should see exactly one Document; tenant B's row is invisible.
    async with tenant_session(a) as db:
        docs_a = (await db.execute(select(Document))).scalars().all()
    async with tenant_session(b) as db:
        docs_b = (await db.execute(select(Document))).scalars().all()
    assert len(docs_a) == 1
    assert len(docs_b) == 1
    assert {d.tenant_id for d in docs_a} == {a}
    assert {d.tenant_id for d in docs_b} == {b}
