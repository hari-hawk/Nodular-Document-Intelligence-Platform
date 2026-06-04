"""Ingest — multi-format parser.

Routes by MIME / extension to the right parser and returns a uniform
`IngestedDocument`. PDFs are text-extracted first; only the pages that
look scanned (no extractable text) get marked for vision routing.
"""
from __future__ import annotations

import hashlib
import io
import mimetypes
from pathlib import Path
from typing import BinaryIO

from mdi.kernel.observability import get_logger
from mdi.models.schemas import IngestedDocument

logger = get_logger(__name__)


class UnsupportedFormatError(ValueError):
    """Raised for file types we explicitly do not handle."""


# Extensions we route. Anything else falls through to UnsupportedFormatError.
_TEXT_EXT = {".txt", ".md", ".log"}
_PDF_EXT = {".pdf"}
_DOCX_EXT = {".docx"}
_XLSX_EXT = {".xlsx", ".xls"}
_CSV_EXT = {".csv", ".tsv"}
_IMG_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".gif"}


def sniff_mime(filename: str) -> str:
    mime, _ = mimetypes.guess_type(filename)
    return mime or "application/octet-stream"


def _ext(filename: str) -> str:
    return Path(filename).suffix.lower()


# ---------------------------------------------------------------------------
# Format-specific readers
# ---------------------------------------------------------------------------
def _read_pdf(stream: BinaryIO) -> tuple[list[str], int, bool]:
    """Return (pages, page_count, needs_vision)."""
    from pypdf import PdfReader

    reader = PdfReader(stream)
    pages: list[str] = []
    needs_vision = False
    for page in reader.pages:
        text = (page.extract_text() or "").strip()
        if not text:
            needs_vision = True
        pages.append(text)
    return pages, len(reader.pages), needs_vision


def _read_docx(stream: BinaryIO) -> tuple[list[str], int]:
    from docx import Document  # type: ignore[import-not-found]

    doc = Document(stream)
    text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    return [text], 1


def _read_xlsx(stream: BinaryIO) -> tuple[list[str], int]:
    import pandas as pd

    sheets = pd.read_excel(stream, sheet_name=None)
    blocks: list[str] = []
    for name, df in sheets.items():
        blocks.append(f"# Sheet: {name}\n{df.to_csv(index=False)}")
    return ["\n\n".join(blocks)], len(sheets)


def _read_csv(stream: BinaryIO) -> tuple[list[str], int]:
    import pandas as pd

    df = pd.read_csv(stream)
    return [df.to_csv(index=False)], 1


def _read_text(stream: BinaryIO) -> tuple[list[str], int]:
    raw = stream.read()
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
    return [text], 1


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def ingest(filename: str, content: bytes) -> IngestedDocument:
    """Parse `content` according to its filename's extension and return an IngestedDocument."""
    ext = _ext(filename)
    sha = hashlib.sha256(content).hexdigest()
    mime = sniff_mime(filename)
    stream = io.BytesIO(content)

    pages: list[str]
    page_count: int
    needs_vision = False
    images: list[bytes] = []

    if ext in _PDF_EXT:
        pages, page_count, needs_vision = _read_pdf(stream)
    elif ext in _DOCX_EXT:
        pages, page_count = _read_docx(stream)
    elif ext in _XLSX_EXT:
        pages, page_count = _read_xlsx(stream)
    elif ext in _CSV_EXT:
        pages, page_count = _read_csv(stream)
    elif ext in _TEXT_EXT or mime.startswith("text/"):
        pages, page_count = _read_text(stream)
    elif ext in _IMG_EXT or mime.startswith("image/"):
        # Vision-only — no text path.
        pages = []
        page_count = 1
        needs_vision = True
        images = [content]
    else:
        raise UnsupportedFormatError(f"Unsupported file type: {filename!r}")

    text = "\n\n".join(p for p in pages if p) if pages else None
    logger.info(
        "ingest.parsed",
        filename=filename,
        ext=ext,
        page_count=page_count,
        needs_vision=needs_vision,
        bytes=len(content),
    )
    return IngestedDocument(
        filename=filename,
        mime_type=mime,
        bytes=len(content),
        page_count=page_count,
        text=text,
        pages=pages,
        images=images,
        needs_vision=needs_vision,
        sha256=sha,
    )
