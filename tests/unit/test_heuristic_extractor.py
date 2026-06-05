"""Tests for the heuristic / regex-based field extractor.

The Georgetown sample text below is the literal first 280 chars from
one of the NSR Ops PDFs — the parser actually produces this. If those
extractions stop working, real customer documents stop yielding usable
fields when the LLM is unavailable.
"""
from __future__ import annotations

from mdi.brain.heuristic_extractor import (
    _heuristic_customer,
    _heuristic_vendor,
    _normalise_date,
    extract_fields,
    summarise,
)

GEORGETOWN_SAMPLE = """Jun 13, 2025 2:23:59 PM
Shauna Sebastian
Page:  1
No. 2387215
Sold To: Purchased From:
GEORGETOWN PAPER STOCK
Georgetown Paper Stock
1404 Benson Ct
Baltimore, MD 21227
Ship / Inv Date Apr 1, 2025
Rel. / Pickup No
Referrer Ken Brask     0.000 / ST
Payment Terms NET 30
Department"""

ATT_SAMPLE = """AT&T Business Services
Account Number: 0133442501
Invoice Number: ATT-INV-2026-04-7711
Invoice Date: 2026-04-30
Due Date: 2026-05-25

Subtotal: $2,814.82
Tax: $239.26
Total Due: $3,054.08
Currency: USD
"""


class TestGeorgetownExtraction:
    """Georgetown PDF — exact text we saw in the NSR Ops upload."""

    def test_extracts_document_number(self):
        f = extract_fields(GEORGETOWN_SAMPLE)
        assert "document_number" in f
        assert f["document_number"].value == "2387215"

    def test_extracts_vendor(self):
        f = extract_fields(GEORGETOWN_SAMPLE)
        # First all-caps line is "GEORGETOWN PAPER STOCK"
        assert "vendor" in f
        assert "GEORGETOWN" in f["vendor"].value.upper()

    def test_extracts_document_date(self):
        f = extract_fields(GEORGETOWN_SAMPLE)
        assert "document_date" in f
        assert f["document_date"].value == "2025-04-01"

    def test_extracts_payment_terms(self):
        f = extract_fields(GEORGETOWN_SAMPLE)
        assert "payment_terms" in f
        assert "NET 30" in f["payment_terms"].value.upper()

    def test_every_field_has_source_text(self):
        """Source text is the analyst's audit trail — they need to see
        exactly which substring drove each value."""
        f = extract_fields(GEORGETOWN_SAMPLE)
        for k, v in f.items():
            assert v.source_text, f"field {k} has empty source_text"
            assert len(v.source_text) <= 120


class TestATTExtraction:
    """Anchored-pattern path — every field has a 'Label: value' anchor."""

    def test_extracts_document_number_anchored(self):
        f = extract_fields(ATT_SAMPLE)
        assert "document_number" in f
        assert f["document_number"].value == "ATT-INV-2026-04-7711"
        # Anchored pattern → higher confidence than positional fallback
        assert f["document_number"].confidence >= 0.85

    def test_extracts_account_number(self):
        f = extract_fields(ATT_SAMPLE)
        assert "account_number" in f
        assert f["account_number"].value == "0133442501"

    def test_extracts_subtotal_tax_total_as_separate_fields(self):
        f = extract_fields(ATT_SAMPLE)
        assert f["subtotal"].value == 2814.82
        assert f["tax"].value == 239.26
        assert f["total"].value == 3054.08

    def test_extracts_currency(self):
        f = extract_fields(ATT_SAMPLE)
        assert f["currency"].value == "USD"

    def test_extracts_both_dates(self):
        f = extract_fields(ATT_SAMPLE)
        assert f["document_date"].value == "2026-04-30"
        assert f["due_date"].value == "2026-05-25"


class TestDateNormalisation:
    def test_iso_passthrough(self):
        assert _normalise_date("2026-04-30") == "2026-04-30"

    def test_us_slash_format(self):
        assert _normalise_date("04/30/2026") == "2026-04-30"

    def test_two_digit_year(self):
        # 25 → 2025 (the < 50 → 20xx rule)
        assert _normalise_date("4/1/25") == "2025-04-01"
        # 75 → 1975
        assert _normalise_date("4/1/75") == "1975-04-01"

    def test_written_month(self):
        assert _normalise_date("Apr 1, 2025") == "2025-04-01"
        assert _normalise_date("April 30, 2026") == "2026-04-30"

    def test_unparseable_passes_through(self):
        """Better to surface a wonky string than guess + shift dates."""
        assert _normalise_date("sometime next quarter") == "sometime next quarter"


class TestVendorHeuristic:
    def test_first_all_caps_line(self):
        assert _heuristic_vendor("ACME CORP\n123 Main St") == "ACME CORP"

    def test_skips_invoice_header(self):
        text = "INVOICE\nGEORGETOWN PAPER STOCK\n123 Main St"
        assert _heuristic_vendor(text) == "GEORGETOWN PAPER STOCK"

    def test_skips_mostly_lowercase_lines(self):
        # "Georgetown Paper Stock" is mostly lowercase → not vendor
        text = "Georgetown Paper Stock\n1404 Benson Ct"
        assert _heuristic_vendor(text) is None

    def test_skips_too_short(self):
        assert _heuristic_vendor("AC\n123 Main") is None

    def test_skips_too_long(self):
        # > 80 chars
        text = "X" * 100 + "\nACME CORP"
        assert _heuristic_vendor(text) == "ACME CORP"


class TestCustomerHeuristic:
    def test_extracts_after_bill_to(self):
        text = "Bill To: Globex Inc.\n350 Fifth Avenue"
        assert _heuristic_customer(text) == "Globex Inc."

    def test_handles_multiline_separator(self):
        text = "Sold To:\nAcme Manufacturing, Inc.\n4200 Industrial Park Dr"
        assert _heuristic_customer(text) == "Acme Manufacturing, Inc."

    def test_rejects_purchased_from_companion_line(self):
        """Georgetown samples have 'Sold To: Purchased From:' on one line —
        we must not return 'Purchased From:' as the customer."""
        text = "Sold To: Purchased From:\nGEORGETOWN PAPER STOCK"
        result = _heuristic_customer(text)
        assert result is None or "purchased from" not in result.lower()


class TestSummarise:
    def test_flattens_field_extractions(self):
        f = extract_fields(GEORGETOWN_SAMPLE)
        s = summarise(f)
        assert isinstance(s, dict)
        # Values should be raw, not FieldExtraction objects
        assert s["document_number"] == "2387215"

    def test_empty_text_returns_empty_dict(self):
        assert extract_fields("") == {}
        assert extract_fields(None) == {}  # type: ignore[arg-type]
