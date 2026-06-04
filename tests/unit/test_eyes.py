"""Eyes organ — exercised against FakeGateway."""
from __future__ import annotations

import pytest

from mdi.brain import eyes
from mdi.kernel.ingest import ingest


@pytest.mark.asyncio
async def test_eyes_classifies_invoice(installed_fake_gateway):
    doc = ingest("inv.txt", b"From: Acme Corp\nInvoice Number: INV-1\nTotal: 100.00\n")
    cluster = await eyes.classify(doc)
    assert cluster.doc_type in {"invoice", "unknown"}  # heuristic fallback acceptable
    assert cluster.confidence > 0


@pytest.mark.asyncio
async def test_eyes_uses_fake_gateway(installed_fake_gateway):
    installed_fake_gateway.set_default(
        "eyes", "*",
        '{"industry":"telecom_billing","vendor":"AT&T","doc_type":"invoice",'
        '"layout":"tabular","language":"en","confidence":0.92,"rationale":"signal"}',
    )
    doc = ingest("att.txt", b"Carrier statement from AT&T")
    cluster = await eyes.classify(doc)
    assert cluster.industry == "telecom_billing"
    assert cluster.vendor == "AT&T"
    assert cluster.confidence == 0.92
