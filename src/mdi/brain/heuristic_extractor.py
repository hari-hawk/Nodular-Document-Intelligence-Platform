"""Heuristic / deterministic field extractor.

Mirrors what Digital-Direction's `extractor_generic.py` does for telecom
invoices: when the LLM is rate-limited (free-tier daily cap on Gemini,
network outage, intentional offline mode), pull obvious invoice / claim
fields out of the parsed document text using a stack of regex patterns.

Confidence scoring:
  - 0.85 — pattern has a strong anchor word ("Invoice #", "Total Due")
  - 0.70 — pattern is positional ("No. <num>" near top of page)
  - 0.55 — pattern is a weak fallback ("first all-caps line as vendor")
  - 0.40 — pattern uncertain ("anything that looks like a date")

The extracted FieldExtraction carries the matched text via `source_text`
so analysts can see exactly which substring drove each value. That's
the same provenance contract the LLM-based extractor uses.

Why a separate module + not just inline in Hands:
  - Pure functions, no async, no LLM gateway — trivially unit-testable.
  - Can be invoked manually from a re-extract endpoint or from a
    backfill script without standing up the full pipeline.
  - When the LLM IS available, Hands can still run it AND merge — the
    heuristic provides a "second opinion" that catches LLM omissions.
"""
from __future__ import annotations

import re
from typing import Any

from mdi.models.schemas import FieldExtraction

# ─────────────────────────────────────────────────────────────────────────────
# Pattern catalogue — each entry is (regex, confidence, capture_group).
# Listed in priority order; the first matching pattern per field wins.
# ─────────────────────────────────────────────────────────────────────────────

_DOC_NUMBER_PATTERNS: list[tuple[str, float]] = [
    (r"(?:Invoice|Bill|Statement)\s*(?:#|Number|No\.?)\s*[:#]?\s*([A-Z0-9][A-Z0-9\-_/]{3,})", 0.85),
    (r"(?:Claim|Document|Doc|PO|Order)\s*(?:#|Number|No\.?)\s*[:#]?\s*([A-Z0-9][A-Z0-9\-_/]{3,})", 0.85),
    # "No. 2387215" — common on worksheets/receipts
    (r"\bNo\.?\s+([A-Z0-9]{4,}[A-Z0-9\-_/]*)", 0.75),
    # Bracketed: [INV-1234] or (CLM-2026-1234)
    (r"[\[(]([A-Z]{2,}[-_][\w-]{4,})[\])]", 0.70),
]

_DATE_PATTERNS: list[tuple[str, float, str]] = [
    # Anchored: "Invoice Date: 2026-04-30"
    (r"(?:Invoice|Bill|Statement|Document|Issue)\s+Date\s*[:#]?\s*"
     r"((?:\d{4}[-/]\d{1,2}[-/]\d{1,2})|"
     r"(?:\d{1,2}[-/]\d{1,2}[-/]\d{2,4})|"
     r"(?:[A-Z][a-z]+\s+\d{1,2},?\s+\d{4}))", 0.85, "document_date"),
    # "Ship / Inv Date Apr 1, 2025"
    (r"(?:Ship\s*/\s*Inv|Inv\s*Date)\s+"
     r"([A-Z][a-z]+\s+\d{1,2},?\s+\d{4})", 0.80, "document_date"),
    (r"(?:Due|Payment)\s+Date\s*[:#]?\s*"
     r"((?:\d{4}[-/]\d{1,2}[-/]\d{1,2})|"
     r"(?:\d{1,2}[-/]\d{1,2}[-/]\d{2,4})|"
     r"(?:[A-Z][a-z]+\s+\d{1,2},?\s+\d{4}))", 0.85, "due_date"),
]

_AMOUNT_PATTERNS: list[tuple[str, float, str]] = [
    # "Grand Total $3054.08" — listed first as strongest signal
    (r"Grand\s+Total\s*[:#]?\s*\$?\s*([\d,]+\.\d{2})", 0.90, "total"),
    # "Subtotal: $2,814.82" — listed BEFORE generic Total so it gets
    # credited to `subtotal` not `total`.
    (r"Subtotal\s*[:#]?\s*\$?\s*([\d,]+\.\d{2})", 0.80, "subtotal"),
    # "Tax: $239.26" — word-boundary on `Tax` so "Subtotal Tax" works
    (r"(?:Sales\s+Tax|VAT|GST|HST|\bTax)\s*[:#]?\s*\$?\s*([\d,]+\.\d{2})", 0.75, "tax"),
    # "Total Due: $3,054.08" / "Amount Due $3054.08"
    # Negative lookbehind on letter so we don't double-credit Subtotal.
    (r"(?<![A-Za-z])(?:Total|Amount)\s*(?:Due|Payable|Owing)?\s*[:#]?\s*"
     r"\$?\s*([\d,]+\.\d{2})", 0.85, "total"),
]

_ACCOUNT_PATTERNS: list[tuple[str, float]] = [
    (r"(?:Account|Customer|Client)\s*(?:#|Number|No\.?|ID)\s*[:#]?\s*"
     r"([A-Z0-9][\w\-]{4,})", 0.85),
    (r"\bAcct\.?\s*(?:#|No\.?)?\s*[:#]?\s*([A-Z0-9][\w\-]{4,})", 0.80),
]

_PAYMENT_TERMS_PATTERNS: list[tuple[str, float]] = [
    (r"Payment\s+Terms\s*[:#]?\s*((?:NET|Net)\s*\d+[^\n]*)", 0.85),
    (r"Terms\s*[:#]?\s*((?:NET|Net)\s*\d+)", 0.75),
    (r"\b(NET\s*\d{1,3})\b", 0.60),
]

_CURRENCY_PATTERNS: list[tuple[str, float]] = [
    (r"\b(USD|EUR|GBP|CAD|AUD|JPY|CHF|CNY|INR)\b", 0.75),
    (r"Currency\s*[:#]?\s*([A-Z]{3})", 0.85),
]

_PHONE_PATTERN = r"\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}"
_EMAIL_PATTERN = r"[\w.+-]+@[\w-]+\.[\w.-]+"


def extract_fields(text: str) -> dict[str, FieldExtraction]:
    """Run every pattern over `text` and return a {field_name: FieldExtraction}
    dict of everything that matched.

    Returns an empty dict if `text` is None/empty — never raises.
    """
    if not text:
        return {}
    out: dict[str, FieldExtraction] = {}

    # Document number
    for pat, conf in _DOC_NUMBER_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            out["document_number"] = FieldExtraction(
                value=m.group(1).strip(),
                confidence=conf,
                source_text=m.group(0)[:120],
            )
            break

    # Dates — multi-field (document_date, due_date)
    for pat, conf, field_name in _DATE_PATTERNS:
        if field_name in out:
            continue
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            out[field_name] = FieldExtraction(
                value=_normalise_date(m.group(1)),
                confidence=conf,
                source_text=m.group(0)[:120],
            )

    # Amounts — multi-field (total, subtotal, tax)
    for pat, conf, field_name in _AMOUNT_PATTERNS:
        if field_name in out:
            continue
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                v = float(m.group(1).replace(",", ""))
                out[field_name] = FieldExtraction(
                    value=v, confidence=conf, source_text=m.group(0)[:120],
                )
            except ValueError:
                continue

    # Account / customer number
    for pat, conf in _ACCOUNT_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            out["account_number"] = FieldExtraction(
                value=m.group(1).strip(),
                confidence=conf,
                source_text=m.group(0)[:120],
            )
            break

    # Payment terms
    for pat, conf in _PAYMENT_TERMS_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            out["payment_terms"] = FieldExtraction(
                value=m.group(1).strip(),
                confidence=conf,
                source_text=m.group(0)[:120],
            )
            break

    # Currency
    for pat, conf in _CURRENCY_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            out["currency"] = FieldExtraction(
                value=m.group(1).upper().strip(),
                confidence=conf,
                source_text=m.group(0)[:60],
            )
            break

    # Phone (first hit; mostly for vendor contact)
    m_phone = re.search(_PHONE_PATTERN, text)
    if m_phone:
        out["phone"] = FieldExtraction(
            value=m_phone.group(0),
            confidence=0.65,
            source_text=m_phone.group(0),
        )

    # Email
    m_email = re.search(_EMAIL_PATTERN, text)
    if m_email:
        out["email"] = FieldExtraction(
            value=m_email.group(0),
            confidence=0.85,
            source_text=m_email.group(0),
        )

    # Vendor heuristic — first all-caps line ≥3 chars, often the company brand
    vendor = _heuristic_vendor(text)
    if vendor:
        out["vendor"] = FieldExtraction(
            value=vendor,
            confidence=0.60,
            source_text=vendor[:120],
        )

    # Customer heuristic — line after "Sold To:" / "Bill To:"
    customer = _heuristic_customer(text)
    if customer:
        out["customer"] = FieldExtraction(
            value=customer,
            confidence=0.70,
            source_text=customer[:120],
        )

    return out


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _normalise_date(raw: str) -> str:
    """Best-effort ISO-8601 normalisation. Returns raw on failure rather
    than guessing — better to surface a wonky string the analyst can
    eyeball than silently shift a date by a month."""
    s = raw.strip()
    # Already ISO-ish?
    m = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$", s)
    if m:
        y, mo, d = m.groups()
        return f"{y}-{int(mo):02d}-{int(d):02d}"
    # US: MM/DD/YYYY or M/D/YY
    m = re.match(r"^(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})$", s)
    if m:
        mo, d, y = m.groups()
        if len(y) == 2:
            y = ("20" if int(y) < 50 else "19") + y
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    # "Apr 1, 2025" / "April 30, 2026"
    months = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    m = re.match(r"^([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})$", s)
    if m:
        mname, d, y = m.groups()
        mo = months.get(mname[:3].lower())
        if mo:
            return f"{int(y):04d}-{mo:02d}-{int(d):02d}"
    return s  # Couldn't parse; pass through unchanged.


def _heuristic_vendor(text: str) -> str | None:
    """The first all-caps line of reasonable length is typically the
    vendor's printed brand name. Skips obvious non-vendor uppercase lines
    (PAGE, INVOICE, RECEIPT, NOTICE, AMOUNT DUE, etc.)."""
    blocklist = {
        "INVOICE", "RECEIPT", "STATEMENT", "BILL", "NOTICE",
        "PAGE", "AMOUNT DUE", "TOTAL DUE", "REMITTANCE",
        "ACCOUNT", "CUSTOMER", "SOLD TO", "PURCHASED FROM",
        "SHIP TO", "BILL TO", "PAYMENT TERMS", "DEPARTMENT",
        "DESCRIPTION", "QUANTITY", "PRICE", "AMOUNT", "TOTAL",
        "USD", "EUR", "GBP", "DATE",
    }
    for line in text.split("\n"):
        s = line.strip()
        if len(s) < 4 or len(s) > 80:
            continue
        # Require at least 3 letters, mostly uppercase, no leading digit
        letters = [c for c in s if c.isalpha()]
        if len(letters) < 3:
            continue
        if sum(1 for c in letters if c.isupper()) / len(letters) < 0.75:
            continue
        if s.upper() in blocklist:
            continue
        if any(b in s.upper() for b in blocklist):
            continue
        return s
    return None


def _heuristic_customer(text: str) -> str | None:
    """Line following 'Sold To:' / 'Bill To:' / 'Customer:'."""
    patterns = [
        r"(?:Sold\s+To|Bill\s+To|Customer|Billed\s+To)\s*[:#]?\s*\n+\s*([^\n]+)",
        r"(?:Sold\s+To|Bill\s+To|Customer|Billed\s+To)\s*[:#]?\s*([^\n]+)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            # Reject empty / "Purchased From" companion line
            if val and len(val) > 2 and "purchased from" not in val.lower():
                return val
    return None


def summarise(fields: dict[str, FieldExtraction]) -> dict[str, Any]:
    """Compact summary for logging — `{field: value}` only, no provenance."""
    return {
        k: (v.value if hasattr(v, "value") else v)
        for k, v in fields.items()
    }
