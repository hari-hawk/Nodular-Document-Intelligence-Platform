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


def _fallback_for(cluster: Cluster) -> Schema:
    """Generic fallback schema — but ALSO augmented with the pack's
    declared fields so a rate-limited Pattern Cortex still gets the
    pack-specific fields onto Hands' extraction surface. Without this
    augmentation, every 429 from gemini-2.5-pro would silently downgrade
    insurance docs back to the base 10-field schema."""
    augmented, slug = _augment_with_pack(cluster, list(_GENERIC_FALLBACK.fields))
    primary_keys = list(_GENERIC_FALLBACK.primary_keys)
    if slug:
        pk = _pack_primary_keys(slug)
        if pk:
            primary_keys = pk
    return Schema(
        fields=augmented,
        primary_keys=primary_keys,
        discovered_from="discovery",
        pack_slug=slug,
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
        return _fallback_for(cluster)

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
        return _fallback_for(cluster)

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
            return _fallback_for(cluster)

        # Wave 4 — pack-augmentation: append the pack's declared fields
        # to whatever the LLM discovered so pack-specific fields
        # (policy_type, coverage_amount, etc.) always land in the
        # schema Hands extracts against. Without this the LLM's
        # open-vocab discovery skips insurance-specific fields it
        # doesn't see strong cues for in the document body.
        fields, pack_slug = _augment_with_pack(cluster, fields)
        primary_keys = list(data.get("primary_keys", []))
        # If the pack declares primary_keys (e.g. insurance: policy_number)
        # and the LLM didn't, prefer the pack's authoritative list.
        if pack_slug and not primary_keys:
            primary_keys = _pack_primary_keys(pack_slug)

        return Schema(
            fields=fields,
            primary_keys=primary_keys,
            discovered_from="discovery",
            pack_slug=pack_slug,
        )
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("pattern_cortex.parse_error", error=str(e))
        return _fallback_for(cluster)


# ─────────────────────────────────────────────────────────────────────────────
# Pack-augmentation helpers (Wave 4)
# ─────────────────────────────────────────────────────────────────────────────
def _augment_with_pack(
    cluster: Cluster,
    discovered: list[FieldDef],
) -> tuple[list[FieldDef], str | None]:
    """If a pack's industry matches the cluster, append any pack-declared
    fields the LLM didn't surface. Returns the augmented field list plus
    the resolved pack_slug (None when no pack matched).

    Failure is non-fatal: if pack-loading errors, the LLM-discovered
    schema is returned unchanged.
    """
    try:
        pack_slug = _resolve_pack_for_cluster(cluster)
        if not pack_slug:
            return discovered, None
        from mdi.kernel.pack_loader import load_pack
        pack = load_pack(pack_slug)
        pack_fields = (pack.field_schema() or {}).get("fields") or []
        existing = {f.name for f in discovered}
        for raw in pack_fields:
            name = raw.get("name")
            ftype = raw.get("type")
            if not name or not ftype or name in existing:
                continue
            try:
                discovered.append(FieldDef(
                    name=name,
                    type=ftype,
                    required=bool(raw.get("required", False)),
                    description=str(raw.get("description", "")),
                    examples=list(raw.get("examples", [])),
                ))
                existing.add(name)
            except (ValueError, TypeError):
                continue
        return discovered, pack_slug
    except Exception as e:
        logger.warning("pattern_cortex.pack_augment_failed", error=str(e))
        return discovered, None


def _resolve_pack_for_cluster(cluster: Cluster) -> str | None:
    """Find the pack slug whose `industry` matches cluster.industry.

    Pack slugs and industry strings often coincide (insurance pack has
    industry="insurance"), so this is cheap. Returns None if no pack
    matches — the LLM's open-vocab schema is then used as-is.
    """
    try:
        from mdi.kernel.pack_loader import list_packs, load_pack
        # Fast path — try direct slug match first (common case).
        slug = (cluster.industry or "").strip().lower()
        if not slug:
            return None
        for s in list_packs():
            try:
                p = load_pack(s)
            except Exception:
                continue
            if (p.manifest.get("industry") or s) == slug:
                return s
        return None
    except Exception:
        return None


def _pack_primary_keys(pack_slug: str) -> list[str]:
    try:
        from mdi.kernel.pack_loader import load_pack
        schema = load_pack(pack_slug).field_schema() or {}
        keys = schema.get("primary_keys") or []
        return [str(k) for k in keys]
    except Exception:
        return []
