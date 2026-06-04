"""Pack loader — finds and parses business_documents_base."""
from __future__ import annotations

from mdi.kernel import pack_loader


def test_business_documents_base_loads():
    pack = pack_loader.load_pack("business_documents_base")
    assert pack.version == "1.0.0"
    assert "extract_prompts" in pack.manifest
    schema = pack.field_schema()
    assert {f["name"] for f in schema["fields"]} >= {"vendor", "total"}
    validators = pack.validators()
    assert any(v["rule_id"] == "total_equals_subtotal_plus_tax" for v in validators)


def test_list_packs_includes_default():
    assert "business_documents_base" in pack_loader.list_packs()


def test_invoice_prompt_loads():
    pack = pack_loader.load_pack("business_documents_base")
    text = pack.prompt("invoice")
    assert "Invoice extraction" in text
