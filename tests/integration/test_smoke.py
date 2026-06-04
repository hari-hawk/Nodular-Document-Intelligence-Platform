"""Phase-1 smoke test.

Goal (per kickoff prompt §Phase 1, item 10):
  Round-trip a single sample document through ingest -> llm_gateway
  (FakeGateway) -> all 19 stages -> assemble BatchReport.

Persist=False so this test runs without Postgres. The two-tenant RLS
test lives in `test_two_tenant_isolation.py` and IS marked integration.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

SAMPLE_INVOICE = b"""From: Acme Corp
Bill To: Globex Inc.
Invoice Number: INV-1001
Date: 2026-04-15
Due Date: 2026-05-15
Currency: USD

Subtotal: 1150.00
Tax: 84.56
Total: 1234.56
"""


@pytest.mark.asyncio
async def test_smoke_single_document(installed_fake_gateway):
    """Single PDF (well, .txt) round-trips end-to-end and produces a BatchReport."""
    from mdi.orchestrator.pipeline import run_batch_async

    tenant_id = str(uuid4())
    report = await run_batch_async(
        tenant_id=tenant_id,
        payloads=[{"filename": "sample_invoice.txt", "content": SAMPLE_INVOICE}],
        persist=False,
    )

    # Top-level shape
    assert "documents" in report
    assert "extractions" in report
    assert "narrator_summary" in report
    assert len(report["documents"]) == 1

    # FakeGateway ships a default extraction with these fields
    extractions = list(report["extractions"].values())
    assert len(extractions) == 1
    fields = extractions[0]["fields"]
    assert "vendor" in fields
    assert fields["vendor"]["value"] == "Acme Corp"
    assert fields["total"]["value"] == 1234.56

    # Pipeline emitted progress events for every meaningful stage
    progress_lines = report["progress"]
    stages = {int(line.split("]")[0].lstrip("[")) for line in progress_lines}
    # Per-doc stages 1-9 plus batch 10/11/12/13 plus 14/15/16
    for required in (1, 2, 7, 8, 10, 11, 12, 13, 14, 15, 16):
        assert required in stages, f"missing progress for stage {required}"

    # Conscience invented rules are gated → no anomalies marked invented
    invented_anomalies = [a for a in report["anomalies"] if a.get("invented")]
    assert invented_anomalies == []

    # Narrator emitted some text
    assert isinstance(report["narrator_summary"], str)
    assert report["narrator_summary"]


@pytest.mark.asyncio
async def test_smoke_emits_audit_log_payload(installed_fake_gateway):
    """The pipeline includes audit-friendly metadata in its progress trail."""
    from mdi.orchestrator.pipeline import run_batch_async

    report = await run_batch_async(
        tenant_id=str(uuid4()),
        payloads=[{"filename": "sample.txt", "content": SAMPLE_INVOICE}],
        persist=False,
    )
    # Cost is tracked even with persist=False (FakeGateway counts tokens).
    assert report["total_cost_usd"] >= 0
    # Reflection is always produced.
    assert report["reflections"]
    assert report["reflections"][0]["verdict"] in {"strong", "watch", "weak"}
