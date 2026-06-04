"""Unit tests for the corrections-as-pgvector surface (Wave 2.3).

The DB-touching paths (embed_correction, lookup_corrections_semantic)
need real Postgres + pgvector — they're exercised in the integration
suite when DB is reachable. Here we lock in the SENTENCE shape, since
the embedding quality depends on it being stable across deployments.
"""
from __future__ import annotations

from mdi.brain.hippocampus import Hippocampus


def test_correction_sentence_canonical_shape():
    """The embedded sentence is what the model sees — if its shape
    drifts, all stored embeddings become misaligned with new queries.
    Lock it in."""
    s = Hippocampus._correction_sentence(
        industry="telecom_billing",
        vendor="AT&T Business Services",
        doc_type="invoice",
        field_path="total",
        extracted_value="3054.08",
        corrected_value="3054.10",
    )
    assert "telecom_billing" in s
    assert "invoice" in s
    assert "AT&T Business Services" in s
    assert "total" in s
    assert "3054.08" in s
    assert "3054.10" in s
    # Sentence-prose form, not KV-soup — bge-m3 handles English best
    assert "from" in s and "but corrected to" in s


def test_correction_sentence_handles_missing_extracted_value():
    """An analyst can record a correction for a field that wasn't
    extracted at all (typical for required fields the LLM missed).
    The sentence should still build."""
    s = Hippocampus._correction_sentence(
        industry="healthcare_claims",
        vendor="BlueCross",
        doc_type="claim_837",
        field_path="provider_npi",
        extracted_value=None,
        corrected_value="1487654329",
    )
    assert "(no value)" in s
    assert "1487654329" in s


def test_correction_sentence_under_embedding_budget():
    """bge-m3 has a ~512-token context but works best <256 chars.
    Our sentence shape should comfortably stay under that even with
    long vendor names."""
    s = Hippocampus._correction_sentence(
        industry="business_services_consulting_outsourcing_etc",
        vendor="A Quite Long Vendor Company Holdings, LLC International",
        doc_type="master_service_agreement_renewal_addendum",
        field_path="total_contract_value_in_local_currency",
        extracted_value="A" * 50,
        corrected_value="B" * 50,
    )
    assert len(s) < 400  # leaves headroom; typical sentences are <200
