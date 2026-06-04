"""Ingest unit tests — text formats only (PDF/DOCX/XLSX exercised in integration)."""
from __future__ import annotations

import pytest

from mdi.kernel.ingest import UnsupportedFormatError, ingest


def test_ingest_plain_text():
    content = b"hello world\nthis is a test"
    doc = ingest("note.txt", content)
    assert doc.filename == "note.txt"
    assert doc.text == "hello world\nthis is a test"
    assert doc.page_count == 1
    assert doc.bytes == len(content)
    assert doc.sha256 is not None
    assert doc.needs_vision is False


def test_ingest_csv():
    content = b"name,total\nAcme,100\nGlobex,200\n"
    doc = ingest("rows.csv", content)
    assert "Acme" in (doc.text or "")
    assert doc.page_count == 1


def test_ingest_image_routes_to_vision():
    # Magic 1x1 PNG (no real image content needed for routing test).
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\x00"
        b"\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    doc = ingest("logo.png", png)
    assert doc.needs_vision is True
    assert doc.images == [png]
    assert doc.text is None


def test_ingest_unsupported():
    with pytest.raises(UnsupportedFormatError):
        ingest("mystery.zip", b"PK\x03\x04")
