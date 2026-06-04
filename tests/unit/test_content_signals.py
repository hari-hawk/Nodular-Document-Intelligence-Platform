"""Tests for the content-signal pack-detection module.

The signal layer is a pre-LLM short-circuit — these tests lock in:
  - required_any matching (case-insensitive substring)
  - doc_type_marker scoring + confidence ladder
  - multi-pattern recognition: multiple packs above threshold all surface
  - regex escape hatches (`re:...` prefix, `/.../i` slashes-flag form)
  - graceful behaviour when a pack has no content_signals
"""
from __future__ import annotations

from mdi.brain.content_signals import (
    SignalMatch,
    clear_caches,
    detect_packs,
)


def setup_function(_):
    clear_caches()


# ─────────────────────────────────────────────────────────────────────────────
# Pack manifest helpers — minimal shape the detector needs.
# ─────────────────────────────────────────────────────────────────────────────
def att_manifest() -> dict:
    return {
        "content_signals": {
            "required_any": ["AT&T", "att.com"],
            "doc_type_markers": {
                "invoice": ["Bill-At-A-Glance", "TotalAmountDue"],
                "csr": ["CUSTOMER SERVICE RECORD"],
            },
        }
    }


def verizon_manifest() -> dict:
    return {
        "content_signals": {
            "required_any": ["Verizon", "vzw.com"],
            "doc_type_markers": {
                "invoice": ["Bill Summary"],
            },
        }
    }


def no_signals_pack() -> dict:
    return {"name": "no_signals_pack"}  # content_signals deliberately absent


# ─────────────────────────────────────────────────────────────────────────────
# required_any behaviour
# ─────────────────────────────────────────────────────────────────────────────
def test_no_required_match_returns_no_match():
    packs = {"att": att_manifest()}
    matches = detect_packs(
        # Deliberately avoid AT&T/att.com substrings in the test prose
        # — otherwise the detector will (correctly!) match the text we
        # wrote to describe a non-match.
        text="This is a Verizon document with no marker phrases.",
        available_packs=packs,
    )
    assert matches == []


def test_required_only_returns_0_75_confidence():
    """When the vendor mark is present but no doc_type markers are,
    confidence is 0.75 (vendor-confident, doc_type still LLM territory)."""
    packs = {"att": att_manifest()}
    matches = detect_packs(
        text="Bill issued by AT&T Business Services for account 0133442501. "
             "Generic billing footer with no doc-type marker phrases.",
        available_packs=packs,
    )
    assert len(matches) == 1
    m = matches[0]
    assert m.pack_slug == "att"
    assert m.confidence == 0.75
    assert m.doc_type_hint is None


def test_required_plus_one_doc_marker_returns_0_90():
    packs = {"att": att_manifest()}
    matches = detect_packs(
        text="AT&T Bill-At-A-Glance summary for the month of April",
        available_packs=packs,
    )
    assert len(matches) == 1
    assert matches[0].confidence == 0.90
    assert matches[0].doc_type_hint == "invoice"


def test_required_plus_two_doc_markers_returns_0_95():
    """Two or more markers for the same doc_type ratchets confidence to 0.95
    — enough that Eyes will short-circuit the LLM classify call."""
    packs = {"att": att_manifest()}
    text = "AT&T Bill-At-A-Glance. TotalAmountDue $123.45."
    matches = detect_packs(text=text, available_packs=packs)
    assert len(matches) == 1
    assert matches[0].confidence == 0.95
    assert matches[0].doc_type_hint == "invoice"


def test_case_insensitive_substring_match():
    """Phrase matching is case-insensitive — Gemini sometimes lowercases
    the vendor mark on OCR'd pages and we must still match."""
    packs = {"att": att_manifest()}
    matches = detect_packs(
        text="footer: at&t — bill-at-a-glance",
        available_packs=packs,
    )
    assert len(matches) == 1
    assert matches[0].pack_slug == "att"


# ─────────────────────────────────────────────────────────────────────────────
# Multi-pattern recognition (Hari, 2026-06-04 addition)
# ─────────────────────────────────────────────────────────────────────────────
def test_multiple_packs_above_threshold_all_returned_sorted():
    """A document that legitimately matches more than one pack — e.g. a
    consolidated invoice from AT&T that contains a Verizon reference in
    the appendix — surfaces all matches above threshold, sorted by
    confidence so the caller can act on the strongest first."""
    packs = {"att": att_manifest(), "verizon": verizon_manifest()}
    text = (
        "AT&T Bill-At-A-Glance for April. "
        "Appendix C: prior carrier was Verizon Bill Summary May 2024."
    )
    matches = detect_packs(text=text, available_packs=packs)
    slugs = [m.pack_slug for m in matches]
    assert "att" in slugs
    assert "verizon" in slugs
    # Sort: AT&T has required + 1 doc marker (0.90), Verizon has required
    # + 1 doc marker (0.90) — tied, so order is stable.
    assert matches[0].confidence >= matches[-1].confidence


def test_min_confidence_drops_weak_matches():
    """Caller can raise the threshold to suppress vendor-only (0.75) hits."""
    packs = {"att": att_manifest()}
    text = "AT&T footer with no doc-type marker"
    weak = detect_packs(text=text, available_packs=packs)
    assert len(weak) == 1
    strong_only = detect_packs(text=text, available_packs=packs, min_confidence=0.85)
    assert strong_only == []


# ─────────────────────────────────────────────────────────────────────────────
# Backward compat — packs without content_signals
# ─────────────────────────────────────────────────────────────────────────────
def test_packs_without_signals_are_silently_ignored():
    """Existing packs that don't define content_signals contribute zero
    matches — the LLM classifier handles them, same as before."""
    packs = {"att": att_manifest(), "no_signals_pack": no_signals_pack()}
    matches = detect_packs(
        text="AT&T Bill-At-A-Glance for April",
        available_packs=packs,
    )
    assert {m.pack_slug for m in matches} == {"att"}


def test_empty_text_returns_no_match():
    matches = detect_packs(text=None, available_packs={"att": att_manifest()})
    assert matches == []


# ─────────────────────────────────────────────────────────────────────────────
# Regex escape hatches
# ─────────────────────────────────────────────────────────────────────────────
def test_re_prefix_treated_as_regex():
    """`re:pattern` is the escape hatch for structured codes like account
    numbers, where substring won't work."""
    packs = {
        "att": {
            "content_signals": {
                "required_any": [r"re:\d{3}\s+\d{3}-\d{4}\s+\d{3}"],
                "doc_type_markers": {},
            }
        }
    }
    matches = detect_packs(
        text="ACCOUNT 555 123-4567 890 1 BILLDATE",
        available_packs=packs,
    )
    assert len(matches) == 1


def test_slashes_form_regex_with_i_flag():
    """`/pattern/i` — DD's carrier.yaml convention. Trailing `i` is
    case-insensitive, no trailing flag is exact case."""
    packs = {
        "att": {
            "content_signals": {
                "required_any": ["/centrex.*contract/i"],
                "doc_type_markers": {},
            }
        }
    }
    matches = detect_packs(
        text="CENTREX Master Service contract for 2026",
        available_packs=packs,
    )
    assert len(matches) == 1


def test_malformed_regex_silently_fails():
    """A pack with a broken regex shouldn't break detection for other
    packs — bad signal entries are skipped."""
    packs = {
        "broken": {
            "content_signals": {
                "required_any": ["re:[unclosed"],
                "doc_type_markers": {},
            }
        },
        "att": att_manifest(),
    }
    matches = detect_packs(
        text="AT&T Bill-At-A-Glance",
        available_packs=packs,
    )
    assert {m.pack_slug for m in matches} == {"att"}


def test_signal_match_is_a_dataclass_with_expected_fields():
    """Sanity on the public shape — downstream consumers depend on these
    attribute names; locking them in protects against silent rename."""
    packs = {"att": att_manifest()}
    matches = detect_packs(text="AT&T", available_packs=packs)
    m = matches[0]
    assert isinstance(m, SignalMatch)
    assert isinstance(m.pack_slug, str)
    assert isinstance(m.confidence, float)
    assert isinstance(m.matched_phrases, tuple)
    assert isinstance(m.rationale, str)
