"""Pattern Cortex — schema discovery (Stage 4).

Skipped on memory hit. Otherwise uses Gemini Pro to propose a Schema
(field list with types) inferred from the document content. Falls back
to a generic invoice-shaped schema if the LLM is unavailable.
"""
from __future__ import annotations

import json

from mdi.kernel.llm_gateway import GatewayLike, get_gateway
from mdi.kernel.observability import get_logger
from mdi.models.schemas import Cluster, FieldDef, IngestedDocument, Schema

logger = get_logger(__name__)

SYSTEM_PROMPT = """You are the schema discovery organ. Inspect the document and propose a
field schema for extracting its key data. Each field must have a name (lower_snake_case),
a type (one of: string, number, date, currency, boolean, list, object), and a one-line
description. Mark a field as required only when the document type strongly implies it.

Return ONLY a JSON object: {"fields": [{"name", "type", "required", "description"}], "primary_keys": [...]}.
"""

_GENERIC_FALLBACK = Schema(
    fields=[
        FieldDef(name="vendor", type="string", required=True, description="Issuer / counterparty"),
        FieldDef(name="customer", type="string", required=False, description="Recipient if present"),
        FieldDef(name="document_number", type="string", required=False, description="Invoice / PO / contract number"),
        FieldDef(name="document_date", type="date", required=False, description="Document issue date"),
        FieldDef(name="due_date", type="date", required=False, description="Payment / expiry date"),
        FieldDef(name="currency", type="string", required=False, description="ISO 4217 code"),
        FieldDef(name="subtotal", type="currency", required=False, description="Pre-tax amount"),
        FieldDef(name="tax", type="currency", required=False, description="Tax amount"),
        FieldDef(name="total", type="currency", required=False, description="Grand total"),
        FieldDef(name="line_items", type="list", required=False, description="List of line item objects"),
    ],
    primary_keys=["document_number"],
    discovered_from="discovery",
)


async def discover(
    doc: IngestedDocument,
    cluster: Cluster,
    *,
    gateway: GatewayLike | None = None,
) -> Schema:
    gw = gateway or get_gateway()
    body = (doc.text or "")[:12000]
    if not body and not doc.images:
        return _GENERIC_FALLBACK

    prompt = (
        f"INDUSTRY: {cluster.industry}\nVENDOR: {cluster.vendor}\nDOC_TYPE: {cluster.doc_type}\n\n"
        f"DOCUMENT:\n{body}\n"
    )
    try:
        resp = await gw.generate(
            organ="pattern_cortex",
            tier="reasoning",
            system=SYSTEM_PROMPT,
            prompt=prompt,
            json_mode=True,
            max_output_tokens=4096,
            temperature=0.1,
        )
    except Exception as e:
        logger.warning("pattern_cortex.gateway_error", error=str(e))
        return _GENERIC_FALLBACK

    try:
        data = json.loads(resp.text)
        # Sanitize: keep only known FieldDef keys. LLMs often add extras
        # ('schema', 'aliases', 'enum'); we drop them rather than failing.
        allowed = {"name", "type", "required", "description", "examples"}
        type_fixups = {
            "money": "currency", "decimal": "number", "float": "number",
            "int": "number", "integer": "number", "text": "string",
            "datetime": "date", "timestamp": "date", "array": "list",
            "dict": "object", "map": "object",
        }
        fields: list[FieldDef] = []
        for raw in data.get("fields", []):
            if not isinstance(raw, dict):
                continue
            cleaned = {k: v for k, v in raw.items() if k in allowed}
            if "type" in cleaned:
                cleaned["type"] = type_fixups.get(str(cleaned["type"]).lower(), cleaned["type"])
            if "name" not in cleaned or "type" not in cleaned:
                continue
            try:
                fields.append(FieldDef.model_validate(cleaned))
            except ValueError:
                continue
        if not fields:
            return _GENERIC_FALLBACK
        return Schema(
            fields=fields,
            primary_keys=list(data.get("primary_keys", [])),
            discovered_from="discovery",
        )
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("pattern_cortex.parse_error", error=str(e))
        return _GENERIC_FALLBACK
