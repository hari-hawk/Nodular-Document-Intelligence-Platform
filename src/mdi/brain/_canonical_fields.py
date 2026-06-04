"""Field-name normalisation — single source of truth.

Open-vocabulary mode means each LLM call may emit a slightly different
name for the same logical field: `vendor` vs `vendor_name` vs `issuer`.
This module collapses those variants into a canonical set so downstream
consumers (API responses, exports, the UI grid, ad-hoc SQL) see one name
per concept regardless of which LLM did the extraction.

Where this runs
---------------
At the orchestrator boundary, right after Hands returns an Extraction
and before the Extraction is persisted to Postgres. Schema discovery
(Pattern Cortex) keeps the LLM's raw names because the Patterns tab
is meant to reflect what the brain actually saw.

Conflict handling
-----------------
If two raw names collapse to the same canonical name (e.g. both
`vendor` and `vendor_name` appear in one Extraction), we keep the
field with the higher `confidence`. Source provenance moves with the
winning field; the losing field is dropped.
"""
from __future__ import annotations

from collections.abc import Mapping

from mdi.models.schemas import Extraction, FieldExtraction

# Alias map — left side = raw LLM emission, right side = canonical name.
# Add new aliases here, not in the orchestrator or the UI.
ALIASES: dict[str, str] = {
    # Vendor / counterparty
    "vendor_name": "vendor",
    "issuer": "vendor",
    "service_provider": "vendor",
    "biller": "vendor",
    "supplier": "vendor",
    "supplier_name": "vendor",  # Gemini emits flat snake_case on POs sometimes
    "seller": "vendor",

    # Customer / billed party
    "customer_name": "customer",
    "bill_to": "customer",
    "buyer": "customer",
    "buyer_name": "customer",  # Gemini emits flat snake_case on POs sometimes
    "billed_party": "customer",

    # Document numbers
    "invoice_number": "document_number",
    "invoice_id": "document_number",  # Gemini emits this on AT&T + AWS invoices
    "po_number": "document_number",
    "contract_number": "document_number",
    "claim_number": "document_number",
    "agreement_number": "document_number",
    "statement_number": "document_number",
    "receipt_number": "document_number",

    # Dates
    "invoice_date": "document_date",
    "claim_date": "document_date",
    "effective_date": "document_date",
    "issue_date": "document_date",
    "statement_date": "document_date",
    "expiration_date": "due_date",
    "payment_due_date": "due_date",

    # Amounts
    "total_amount": "total",
    "total_amount_due": "total",  # Gemini emits this on Verizon invoices
    "total_due": "total",
    "total_charge": "total",
    "total_contract_value": "total",
    "grand_total": "total",
    "amount_due": "total",
    "tax_amount": "tax",

    # Accounts
    "account_no": "account_number",
    "acct_number": "account_number",
}


def canonical_name(raw: str) -> str:
    """Return the canonical name for `raw`, or `raw` unchanged if not aliased."""
    return ALIASES.get(raw.lower().strip(), raw.lower().strip())


def normalize_extraction(extraction: Extraction) -> Extraction:
    """Return a copy of `extraction` with canonical field names.

    Idempotent: feeding an already-canonical extraction in returns an
    equivalent extraction out. Confidence is the tiebreaker when two raw
    names collapse onto the same canonical name.
    """
    canonical: dict[str, FieldExtraction] = {}
    for raw_name, field in extraction.fields.items():
        cname = canonical_name(raw_name)
        existing = canonical.get(cname)
        if existing is None or field.confidence > existing.confidence:
            canonical[cname] = field
    return extraction.model_copy(update={"fields": canonical})


def normalize_field_keys(fields: Mapping[str, object]) -> dict[str, object]:
    """Light helper for callers that hold a raw dict, not an Extraction.

    Used by exports / UI helpers where reconstructing a full Extraction
    is overkill.
    """
    out: dict[str, object] = {}
    for raw_name, value in fields.items():
        cname = canonical_name(raw_name)
        if cname not in out:
            out[cname] = value
    return out
