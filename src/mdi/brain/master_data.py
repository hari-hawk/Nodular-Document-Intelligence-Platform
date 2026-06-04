"""Master data — per-tenant knowledge that survives across batches.

The tenant_facts table stores stable per-customer truths like "account
0133442501 is owned by Globex Inc." or "MSA-2024-09 expires 2026-03-31".
These get extracted from one batch and biased into the NEXT batch's
extraction so we don't re-discover the same facts every month.

Three operations:
  - record_fact: UPSERT a (fact_type, key) → value. Subsequent sightings
    bump sighting_count + last_seen_at; the value is replaced only if
    the new confidence is strictly higher than the stored one (otherwise
    a single low-confidence emission can't overwrite a high-confidence
    fact recorded earlier).
  - get_facts: list all facts for the current tenant, optionally
    filtered by fact_type.
  - get_fact: single-key lookup, returns None if absent.

Wiring (orchestrator):
  After each extraction is persisted, the orchestrator calls
  record_fact() for a few high-signal pairs derived from the
  extraction: (account → vendor), (document_number → vendor),
  (vendor → customer), etc. Future batches use get_facts() in Stage 6
  (correction lookup) to seed Hands' prompt with known truths.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from mdi.kernel.observability import get_logger

logger = get_logger(__name__)


async def record_fact(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    fact_type: str,
    key: str,
    value: str,
    confidence: float = 0.5,
    source_doc_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """UPSERT a fact. Never raises — fact recording is opportunistic.

    Conflict semantics:
      - Same (tenant, fact_type, key) → bump sighting_count, refresh
        last_seen_at, refresh source_doc_id.
      - Value is OVERWRITTEN only when new confidence > stored. This
        protects high-confidence facts from being clobbered by a noisy
        later emission.
    """
    try:
        row = (await db.execute(sql_text(
            """
            INSERT INTO tenant_facts
                (tenant_id, fact_type, key, value, confidence, source_doc_id)
            VALUES
                (:tenant_id, :ft, :k, :v, :conf, :src)
            ON CONFLICT (tenant_id, fact_type, key) DO UPDATE
                SET sighting_count = tenant_facts.sighting_count + 1,
                    last_seen_at   = NOW(),
                    source_doc_id  = COALESCE(EXCLUDED.source_doc_id,
                                              tenant_facts.source_doc_id),
                    value = CASE
                        WHEN EXCLUDED.confidence > tenant_facts.confidence
                            THEN EXCLUDED.value
                            ELSE tenant_facts.value
                    END,
                    confidence = GREATEST(
                        tenant_facts.confidence, EXCLUDED.confidence
                    )
            RETURNING id::text, sighting_count, value, confidence
            """
        ), {
            "tenant_id": str(tenant_id),
            "ft": fact_type, "k": key, "v": value,
            "conf": float(confidence),
            "src": str(source_doc_id) if source_doc_id else None,
        })).first()
    except Exception as exc:
        logger.warning(
            "tenant_facts.upsert_failed",
            fact_type=fact_type, key=key[:80], error=str(exc),
        )
        return {"recorded": False, "reason": f"db error: {exc}"}
    return {
        "recorded": True,
        "id": row[0],
        "sighting_count": row[1],
        "value": row[2],
        "confidence": float(row[3]),
    }


async def get_facts(
    db: AsyncSession,
    *,
    fact_type: str | None = None,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """List facts for the current RLS tenant context.

    `fact_type` filter is optional; pass None to list everything (the
    /admin/tenant-facts endpoint uses that path).
    """
    if fact_type is None:
        rows = (await db.execute(sql_text(
            "SELECT id::text, fact_type, key, value, confidence, "
            "       source_doc_id::text, sighting_count, "
            "       last_seen_at, created_at "
            "FROM tenant_facts "
            "ORDER BY confidence DESC, sighting_count DESC, last_seen_at DESC "
            "LIMIT :limit"
        ), {"limit": int(limit)})).all()
    else:
        rows = (await db.execute(sql_text(
            "SELECT id::text, fact_type, key, value, confidence, "
            "       source_doc_id::text, sighting_count, "
            "       last_seen_at, created_at "
            "FROM tenant_facts WHERE fact_type = :ft "
            "ORDER BY confidence DESC, sighting_count DESC, last_seen_at DESC "
            "LIMIT :limit"
        ), {"ft": fact_type, "limit": int(limit)})).all()

    return [
        {
            "id": r[0], "fact_type": r[1], "key": r[2], "value": r[3],
            "confidence": float(r[4]),
            "source_doc_id": r[5],
            "sighting_count": r[6],
            "last_seen_at": str(r[7]),
            "created_at": str(r[8]),
        }
        for r in rows
    ]


async def get_fact(
    db: AsyncSession,
    *,
    fact_type: str,
    key: str,
) -> dict[str, Any] | None:
    """Single-key lookup. Returns the fact dict or None."""
    row = (await db.execute(sql_text(
        "SELECT id::text, fact_type, key, value, confidence, "
        "       source_doc_id::text, sighting_count, "
        "       last_seen_at, created_at "
        "FROM tenant_facts WHERE fact_type = :ft AND key = :k"
    ), {"ft": fact_type, "k": key})).first()
    if row is None:
        return None
    return {
        "id": row[0], "fact_type": row[1], "key": row[2], "value": row[3],
        "confidence": float(row[4]),
        "source_doc_id": row[5],
        "sighting_count": row[6],
        "last_seen_at": str(row[7]),
        "created_at": str(row[8]),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Helper used by the orchestrator: derive a small set of "obvious" facts
# from an extraction without thinking too hard. The full structured-fact
# inference (contract terms, address rollups) would deserve its own
# extraction pass; this is the cheap deterministic seed.
# ─────────────────────────────────────────────────────────────────────────────
def derive_facts_from_extraction(
    extraction_fields: dict[str, Any],
    *,
    document_id: uuid.UUID | None = None,
) -> list[dict[str, Any]]:
    """Map a flat extraction `fields` dict into a list of fact-record
    arguments. Each entry is a kwargs dict for `record_fact()`.

    The rules below are intentionally simple — high-confidence pairs
    only. We can expand once we see what's actually useful in
    production. Pack-specific derivations belong in the pack's
    `enrichment/` directory, not here.
    """
    def _v(name: str) -> Any:
        f = extraction_fields.get(name)
        if isinstance(f, dict) and "value" in f:
            return f["value"]
        if hasattr(f, "value"):
            return f.value  # FieldExtraction
        return f

    facts: list[dict[str, Any]] = []
    vendor = _v("vendor")
    customer = _v("customer")
    account = _v("account_number")
    doc_no = _v("document_number")
    due = _v("due_date")
    governing_law = _v("governing_law")

    if account and vendor:
        facts.append({
            "fact_type": "account", "key": str(account), "value": str(vendor),
            "confidence": 0.85, "source_doc_id": document_id,
        })
    if doc_no and vendor:
        facts.append({
            "fact_type": "document_owner", "key": str(doc_no), "value": str(vendor),
            "confidence": 0.80, "source_doc_id": document_id,
        })
    if vendor and customer:
        facts.append({
            "fact_type": "vendor_customer", "key": str(vendor), "value": str(customer),
            "confidence": 0.70, "source_doc_id": document_id,
        })
    if doc_no and due:
        facts.append({
            "fact_type": "contract_expires", "key": str(doc_no), "value": str(due),
            "confidence": 0.75, "source_doc_id": document_id,
        })
    if vendor and governing_law:
        facts.append({
            "fact_type": "governing_law", "key": str(vendor), "value": str(governing_law),
            "confidence": 0.70, "source_doc_id": document_id,
        })
    return facts
