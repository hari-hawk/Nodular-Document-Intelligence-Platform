"""Unit tests for the auto-pack registry — pure-logic surface.

The DB-touching paths (propose_pack / list_proposals / promote_proposal /
reject_proposal) need an actual Postgres + RLS to exercise meaningfully;
those get covered by the integration suite when DB is reachable. Here
we lock in:
  - the slugify rules
  - the blocklist (the LLM emits "voice" / "internet" as "vendor" sometimes —
    we MUST reject those before they pollute the pack queue)
  - the YAML stub renders to something that re-parses cleanly
"""
from __future__ import annotations

import yaml

from mdi.kernel.auto_pack_registry import (
    _build_stub,
    is_plausible_vendor,
    slugify,
)


class TestSlugify:
    def test_basic_lowercase_and_underscore(self):
        assert slugify("Acme Corp") == "acme_corp"

    def test_ampersand_becomes_and(self):
        # The unique constraint on (tenant_id, vendor_slug) needs slug stability
        # across visual variants — "AT&T" and "ATT" and "at&t" must collapse.
        assert slugify("AT&T") == "at_and_t"
        assert slugify("AT & T") == "at_and_t"

    def test_strips_punctuation_and_collapses_spaces(self):
        assert slugify("Verizon  Business, Inc.") == "verizon_business_inc"

    def test_leading_trailing_underscores_stripped(self):
        assert slugify("  ---Acme---  ") == "acme"

    def test_unicode_falls_through(self):
        # Non-ASCII gets dropped by the [^a-z0-9]+ collapse; not great but
        # consistent — the proposal still stores the original vendor_name
        # for display.
        assert slugify("Société Générale") == "soci_t_g_n_rale"


class TestIsPlausibleVendor:
    def test_accepts_real_vendors(self):
        assert is_plausible_vendor("Acme Corp")[0] is True
        assert is_plausible_vendor("AT&T Business Services")[0] is True
        assert is_plausible_vendor("Globex Inc.")[0] is True

    def test_rejects_blocklisted_generic_nouns(self):
        # These come up as "vendor" candidates from the LLM regularly. They're
        # NOT vendors — they're document line-item labels or service categories.
        for noun in ["voice", "internet", "services", "monthly charges", "tbd", "n/a"]:
            ok, reason = is_plausible_vendor(noun)
            assert ok is False, f"{noun!r} should be rejected"
            assert "blocklist" in (reason or "")

    def test_rejects_too_short(self):
        ok, reason = is_plausible_vendor("AT")
        assert ok is False
        assert "shorter" in (reason or "")

    def test_rejects_too_long(self):
        ok, reason = is_plausible_vendor("A" * 65)
        assert ok is False
        assert "longer" in (reason or "")

    def test_rejects_all_digits(self):
        ok, _reason = is_plausible_vendor("12345")
        assert ok is False

    def test_rejects_empty(self):
        ok, _ = is_plausible_vendor("")
        assert ok is False
        ok, _ = is_plausible_vendor("   ")
        assert ok is False

    def test_case_insensitive_blocklist(self):
        # The LLM doesn't care about case; the blocklist must not either.
        assert is_plausible_vendor("VOICE")[0] is False
        assert is_plausible_vendor("Internet")[0] is False


class TestStubRendering:
    def test_stub_is_valid_yaml_and_carries_metadata(self):
        rendered = _build_stub(
            vendor_slug="acme_corp",
            vendor_name="Acme Corp",
            doc_type_hint="invoice",
        )
        parsed = yaml.safe_load(rendered)
        assert parsed["version"] == "1.0.0"
        assert parsed["name"] == "acme_corp"
        assert parsed["auto_discovered"] is True
        assert parsed["vendor_name"] == "Acme Corp"
        assert parsed["inherits_from"] == "business_documents_base"
        assert parsed["doc_type_hint"] == "invoice"
        # Content signals should at least include the verbatim vendor name
        # so the Wave-1.3 regex detector has something to match on.
        assert "Acme Corp" in parsed["content_signals"]["required_any"]

    def test_stub_handles_yaml_special_chars_in_vendor_name(self):
        # If the LLM emits a vendor name with a double-quote or backslash,
        # the YAML must still parse. This is a regression-protection test.
        rendered = _build_stub(
            vendor_slug="weird_co",
            vendor_name='Weird "Quoted" Co\\back',
            doc_type_hint=None,
        )
        parsed = yaml.safe_load(rendered)
        assert parsed["vendor_name"] == 'Weird "Quoted" Co\\back'

    def test_stub_without_doc_type_hint_omits_the_field(self):
        rendered = _build_stub(
            vendor_slug="acme", vendor_name="Acme",
            doc_type_hint=None,
        )
        parsed = yaml.safe_load(rendered)
        assert "doc_type_hint" not in parsed
