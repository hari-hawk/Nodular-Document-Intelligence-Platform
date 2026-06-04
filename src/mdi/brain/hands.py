"""Hands — extraction (Stage 7).

* Vision routing for scanned PDFs / images (uses `IngestedDocument.images`).
* Correction injection — past corrections matching the cluster scope are
  rendered into the prompt as authoritative hints.
* Per-field confidence + source_text provenance.
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from mdi.kernel.llm_gateway import GatewayLike, get_gateway
from mdi.kernel.observability import get_logger
from mdi.models.schemas import (
    Cluster,
    CorrectionHint,
    Extraction,
    FieldExtraction,
    IngestedDocument,
    Schema,
)

logger = get_logger(__name__)

SYSTEM_PROMPT = """You are the extraction organ. Extract the requested fields from the document.
For every field return:
  - value (use the type implied by the schema)
  - confidence (0..1)
  - source_text (the exact substring you used, when present)
  - page (1-based page index, when known)

If a field is not present in the document, set value to null with confidence 0.

Apply PAST CORRECTIONS unless the document clearly contradicts them.

Return ONLY a JSON object: {"fields": {field_name: {"value", "confidence", "source_text", "page"}}}.
"""


def _render_corrections(corrections: list[CorrectionHint]) -> str:
    if not corrections:
        return ""
    lines = ["PAST CORRECTIONS - apply these unless the document clearly contradicts:"]
    for c in corrections:
        lines.append(
            f"- {c.field_path} should be {c.corrected_value!r} "
            f"(was extracted as {c.extracted_value!r}; user-corrected {c.agreement_count}x)."
            + (f" Note: {c.note}" if c.note else "")
        )
    return "\n".join(lines)


def _render_schema(schema: Schema) -> str:
    lines = ["FIELDS TO EXTRACT:"]
    for f in schema.fields:
        req = " (required)" if f.required else ""
        lines.append(f"  - {f.name}: {f.type}{req} - {f.description}")
    return "\n".join(lines)


async def extract(
    doc: IngestedDocument,
    cluster: Cluster,
    schema: Schema,
    corrections: list[CorrectionHint],
    *,
    pattern_id: UUID | None = None,
    gateway: GatewayLike | None = None,
) -> Extraction:
    gw = gateway or get_gateway()

    body = (doc.text or "")[:24000]
    correction_block = _render_corrections(corrections)
    schema_block = _render_schema(schema)

    prompt = (
        f"CLUSTER: {cluster.industry} | {cluster.vendor} | {cluster.doc_type}\n\n"
        f"{schema_block}\n\n"
        f"{correction_block}\n\n"
        f"DOCUMENT:\n{body}\n"
    )

    used_vision = False
    images: list[bytes] | None = None
    if doc.needs_vision and doc.images:
        used_vision = True
        images = doc.images

    try:
        resp = await gw.generate(
            organ="hands",
            tier="extraction",
            system=SYSTEM_PROMPT,
            prompt=prompt,
            images=images,
            json_mode=True,
            max_output_tokens=4096,
            temperature=0.0,
            tenant_id=None,
        )
    except Exception as e:
        logger.warning("hands.gateway_error", error=str(e))
        return Extraction(document_id=doc.document_id, used_vision=used_vision, pattern_id=pattern_id)

    fields: dict[str, FieldExtraction] = {}
    try:
        data = json.loads(resp.text)
        raw_fields: dict[str, Any] = data.get("fields", {})
        for name, payload in raw_fields.items():
            if not isinstance(payload, dict):
                # Tolerate shorthand: bare value.
                fields[name] = FieldExtraction(value=payload, confidence=0.5)
                continue
            fields[name] = FieldExtraction(
                value=payload.get("value"),
                confidence=float(payload.get("confidence", 0.5) or 0.0),
                source_text=payload.get("source_text"),
                page=payload.get("page"),
            )
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("hands.parse_error", error=str(e), text=resp.text[:200])

    return Extraction(
        document_id=doc.document_id,
        fields=fields,
        cost_usd=resp.call.cost_usd,
        used_vision=used_vision,
        pattern_id=pattern_id,
    )
