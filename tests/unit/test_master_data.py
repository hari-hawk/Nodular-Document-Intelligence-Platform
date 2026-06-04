"""Unit tests for the master-data fact-derivation logic (Wave 2.4).

The DB UPSERT path needs Postgres + RLS — covered by the integration
suite. Here we lock in the pure-function derivation rules: what facts
get extracted from a given Extraction.fields dict.
"""
from __future__ import annotations

import uuid

from mdi.brain.master_data import derive_facts_from_extraction


def _ex(**fields):
    """Mimic an Extraction.fields dict (with FieldExtraction-shaped dicts)."""
    return {k: {"value": v, "confidence": 0.9} for k, v in fields.items()}


def test_account_to_vendor_pair_derived():
    facts = derive_facts_from_extraction(_ex(
        account_number="0133442501",
        vendor="AT&T",
    ))
    types = {f["fact_type"] for f in facts}
    assert "account" in types
    account_fact = next(f for f in facts if f["fact_type"] == "account")
    assert account_fact["key"] == "0133442501"
    assert account_fact["value"] == "AT&T"
    # account → vendor is high-confidence (anchor field semantics)
    assert account_fact["confidence"] >= 0.80


def test_document_owner_pair_derived():
    facts = derive_facts_from_extraction(_ex(
        document_number="INV-1001",
        vendor="Acme Corp",
    ))
    types = {f["fact_type"] for f in facts}
    assert "document_owner" in types


def test_vendor_customer_pair_derived():
    facts = derive_facts_from_extraction(_ex(
        vendor="Verizon",
        customer="Globex Inc.",
    ))
    types = {f["fact_type"] for f in facts}
    assert "vendor_customer" in types
    vc = next(f for f in facts if f["fact_type"] == "vendor_customer")
    # Lower confidence than account — vendor/customer pairs are coarse
    assert vc["confidence"] < 0.80


def test_contract_expiration_pair_derived():
    facts = derive_facts_from_extraction(_ex(
        document_number="MSA-2024-09",
        due_date="2026-03-31",
    ))
    types = {f["fact_type"] for f in facts}
    assert "contract_expires" in types


def test_governing_law_pair_derived():
    facts = derive_facts_from_extraction(_ex(
        vendor="Globex",
        governing_law="State of New York",
    ))
    types = {f["fact_type"] for f in facts}
    assert "governing_law" in types


def test_missing_anchors_produce_no_facts():
    """Partial extractions (missing vendor or missing key) shouldn't
    produce orphan facts."""
    # account_number alone — no vendor → no `account` fact
    facts = derive_facts_from_extraction(_ex(account_number="0133442501"))
    assert facts == []
    # vendor alone — no account, no doc_no, no customer → no facts
    facts = derive_facts_from_extraction(_ex(vendor="AT&T"))
    assert facts == []


def test_source_doc_id_threaded_through():
    """The orchestrator passes document_id; it should land on every
    fact so provenance is queryable."""
    doc_id = uuid.uuid4()
    facts = derive_facts_from_extraction(
        _ex(account_number="0133442501", vendor="AT&T"),
        document_id=doc_id,
    )
    assert facts
    for f in facts:
        assert f["source_doc_id"] == doc_id


def test_field_extraction_objects_unwrapped():
    """The orchestrator may pass FieldExtraction objects rather than
    dicts. The `_v` helper handles both."""
    class _FakeFieldExtraction:
        def __init__(self, value):
            self.value = value

    fields = {
        "vendor": _FakeFieldExtraction("AT&T"),
        "account_number": _FakeFieldExtraction("0133442501"),
    }
    facts = derive_facts_from_extraction(fields)
    assert any(f["fact_type"] == "account" for f in facts)
