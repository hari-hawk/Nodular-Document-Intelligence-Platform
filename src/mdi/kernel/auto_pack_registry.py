"""Auto-pack registry — self-discovered vendor packs.

When Hands extracts a vendor name that isn't covered by any existing
pack, this module proposes a new auto-pack. Proposals start in `pending`
and have ZERO influence on extraction — they're a queue analysts review.
A one-click promotion (POST /admin/auto-packs/{id}/promote) writes a
real `packs/_auto/<slug>/skills.yaml` stub and the next document from
that vendor routes through it.

Design choices:
  - Proposals live in Postgres (RLS-isolated per tenant) so the queue
    integrates with the existing admin UI patterns.
  - Stub packs land in `mdi/packs/_auto/<slug>/` so they're physically
    separated from human-curated packs and easy to bulk-prune later.
  - The blocklist rejects obvious LLM hallucinations early — "voice",
    "internet", "monthly charges" — borrowed from Digital-Direction's
    real-world false-positive set.
  - Multi-sighting accumulates a `sighting_count` so analysts can sort
    "show me the vendors we keep seeing but haven't promoted yet".

Hook into the pipeline: the orchestrator calls `propose_pack()` after
Hands persists an extraction, IF the document's pack was the open-vocab
fallback (business_documents_base). That's the signal we extracted in
generic mode and a vendor-specific pack might be worth creating.
"""
from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from mdi.kernel.observability import get_logger

logger = get_logger(__name__)


# Tokens that the LLM occasionally emits as a "vendor" but which are
# either generic service nouns or document anatomy. Sourced from
# Digital-Direction's blocklist + extras observed in MDI's own evals.
_BLOCKLIST = frozenset(
    s.lower() for s in {
        # Generic service nouns (telecom DD seeded these; generic enough to keep)
        "voice", "internet", "data", "mobility", "wireless", "wireline",
        "broadband", "fiber", "ethernet", "service", "services",
        "telecom", "telecommunications", "carrier", "vendor", "supplier",
        # Document anatomy — these are line-item labels, not vendor names
        "monthly charges", "equipment charges", "taxes", "surcharges", "fees",
        "subtotal", "total", "balance", "amount", "amount due", "currency",
        # Null markers
        "unknown", "n/a", "na", "none", "null", "tbd",
    }
)

_MIN_LEN = 3
_MAX_LEN = 64


def slugify(name: str) -> str:
    """Vendor name → directory-safe slug. Mirrors the convention used by
    `scripts/generate_carrier_registry.py` in Digital-Direction so future
    consolidation between the two registries doesn't need a remap table.
    """
    s = name.lower().strip()
    s = re.sub(r"[&]+", "_and_", s)
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def is_plausible_vendor(name: str) -> tuple[bool, str | None]:
    """Sanity-check a candidate before we accept it as a proposal.

    Returns (ok, reason_if_rejected).
    """
    if not name:
        return False, "empty"
    stripped = name.strip()
    if len(stripped) < _MIN_LEN:
        return False, f"shorter than {_MIN_LEN} chars"
    if len(stripped) > _MAX_LEN:
        return False, f"longer than {_MAX_LEN} chars"
    if stripped.lower() in _BLOCKLIST:
        return False, "blocklisted generic noun"
    if stripped.isdigit():
        return False, "all digits"
    if not re.search(r"[a-zA-Z]", stripped):
        return False, "no alphabetic characters"
    return True, None


async def propose_pack(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    vendor_name: str,
    doc_type_hint: str | None = None,
    first_seen_doc_id: uuid.UUID | None = None,
    sample_extraction: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Insert (or bump the sighting_count of) an auto-pack proposal.

    Returns a status dict so the caller can log / surface the outcome.
    Never raises — pack proposal is opportunistic, not load-bearing.
    """
    ok, reason = is_plausible_vendor(vendor_name)
    if not ok:
        logger.info("auto_pack.rejected", vendor=vendor_name[:80], reason=reason)
        return {"proposed": False, "reason": reason}

    slug = slugify(vendor_name)
    if not slug:
        return {"proposed": False, "reason": "slug empty after normalisation"}

    # Upsert: first sighting inserts; subsequent sightings of the same
    # (tenant, slug) bump sighting_count and refresh last_seen_at — but
    # leave vendor_name / sample_extraction from the first sighting alone
    # so a later malformed sighting can't poison the proposal.
    try:
        row = (await db.execute(sql_text(
            """
            INSERT INTO auto_pack_proposals
                (tenant_id, vendor_slug, vendor_name, doc_type_hint,
                 first_seen_doc_id, sample_extraction)
            VALUES
                (:tenant_id, :slug, :name, :doc_type,
                 :doc_id, CAST(:sample AS JSONB))
            ON CONFLICT (tenant_id, vendor_slug) DO UPDATE
                SET sighting_count = auto_pack_proposals.sighting_count + 1,
                    last_seen_at   = NOW()
            RETURNING id::text, status, sighting_count
            """
        ), {
            "tenant_id": str(tenant_id),
            "slug": slug,
            "name": vendor_name.strip(),
            "doc_type": doc_type_hint,
            "doc_id": str(first_seen_doc_id) if first_seen_doc_id else None,
            "sample": _serialise_sample(sample_extraction),
        })).first()
    except Exception as exc:
        logger.warning("auto_pack.upsert_failed", vendor=vendor_name[:80], error=str(exc))
        return {"proposed": False, "reason": f"db error: {exc}"}

    return {
        "proposed": True,
        "proposal_id": row[0],
        "status": row[1],
        "sighting_count": row[2],
        "slug": slug,
    }


async def list_proposals(
    db: AsyncSession,
    *,
    status_filter: str = "pending",
) -> list[dict[str, Any]]:
    """List auto-pack proposals for the current RLS tenant context.

    `status_filter` is one of pending/approved/rejected/superseded/all.
    """
    if status_filter == "all":
        rows = (await db.execute(sql_text(
            "SELECT id::text, vendor_slug, vendor_name, doc_type_hint, "
            "       sighting_count, status, decided_by, decided_at, "
            "       promoted_path, created_at, last_seen_at "
            "FROM auto_pack_proposals "
            "ORDER BY sighting_count DESC, created_at DESC"
        ))).all()
    else:
        rows = (await db.execute(sql_text(
            "SELECT id::text, vendor_slug, vendor_name, doc_type_hint, "
            "       sighting_count, status, decided_by, decided_at, "
            "       promoted_path, created_at, last_seen_at "
            "FROM auto_pack_proposals WHERE status = :s "
            "ORDER BY sighting_count DESC, created_at DESC"
        ), {"s": status_filter})).all()

    return [
        {
            "id": r[0], "vendor_slug": r[1], "vendor_name": r[2],
            "doc_type_hint": r[3], "sighting_count": r[4],
            "status": r[5], "decided_by": r[6],
            "decided_at": str(r[7]) if r[7] else None,
            "promoted_path": r[8],
            "created_at": str(r[9]),
            "last_seen_at": str(r[10]),
        }
        for r in rows
    ]


async def promote_proposal(
    db: AsyncSession,
    *,
    proposal_id: uuid.UUID,
    decided_by: str,
    packs_root: Path,
) -> dict[str, Any]:
    """Write the stub pack to disk + mark the proposal approved.

    The write happens BEFORE the status flip so the file-system state and
    the DB state never diverge in the approved direction (a partial state
    where DB says approved but stub doesn't exist would be silently wrong;
    DB-rolled-back + stub-on-disk just becomes idempotent on retry).
    """
    proposal = (await db.execute(sql_text(
        "SELECT id::text, vendor_slug, vendor_name, doc_type_hint, status "
        "FROM auto_pack_proposals WHERE id = :id"
    ), {"id": str(proposal_id)})).first()
    if proposal is None:
        return {"promoted": False, "reason": "not_found"}
    if proposal.status != "pending":
        return {"promoted": False, "reason": f"already_{proposal.status}"}

    target_dir = packs_root / "_auto" / proposal.vendor_slug
    target_dir.mkdir(parents=True, exist_ok=True)
    stub_path = target_dir / "skills.yaml"
    stub_path.write_text(_build_stub(
        vendor_slug=proposal.vendor_slug,
        vendor_name=proposal.vendor_name,
        doc_type_hint=proposal.doc_type_hint,
    ))

    await db.execute(sql_text(
        "UPDATE auto_pack_proposals "
        "SET status = 'approved', decided_by = :who, decided_at = NOW(), "
        "    promoted_path = :path "
        "WHERE id = :id"
    ), {"who": decided_by, "id": str(proposal_id), "path": str(stub_path)})

    return {
        "promoted": True,
        "vendor_slug": proposal.vendor_slug,
        "stub_path": str(stub_path),
    }


async def reject_proposal(
    db: AsyncSession,
    *,
    proposal_id: uuid.UUID,
    decided_by: str,
) -> dict[str, Any]:
    """Mark a proposal rejected. Future sightings still bump sighting_count
    (via the UPSERT) but the row stays in `rejected` state so the queue
    isn't polluted."""
    result = await db.execute(sql_text(
        "UPDATE auto_pack_proposals "
        "SET status = 'rejected', decided_by = :who, decided_at = NOW() "
        "WHERE id = :id AND status = 'pending' "
        "RETURNING id::text"
    ), {"who": decided_by, "id": str(proposal_id)})
    row = result.first()
    if row is None:
        return {"rejected": False, "reason": "not_found_or_not_pending"}
    return {"rejected": True}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _serialise_sample(sample: dict[str, Any] | None) -> str | None:
    """JSONB columns take TEXT or NULL via raw SQL. Empty/None → NULL."""
    if not sample:
        return None
    import json
    try:
        return json.dumps(sample, default=str)
    except (TypeError, ValueError):
        return None


def _build_stub(
    *,
    vendor_slug: str,
    vendor_name: str,
    doc_type_hint: str | None,
) -> str:
    """The minimal valid skills.yaml for an auto-discovered pack.

    Inherits prompts/schema/rules from business_documents_base by reference
    so the new pack works on day 1 — analysts then curate vendor-specific
    prompts as the platform sees more documents from this vendor.
    """
    discovered_at = datetime.now(UTC).isoformat(timespec="seconds")
    doc_hint_line = f"\ndoc_type_hint: {doc_type_hint}" if doc_type_hint else ""
    return (
        "version: 1.0.0\n"
        f"name: {vendor_slug}\n"
        "description: |\n"
        f"  Auto-discovered pack for {vendor_name}.\n"
        f"  Created by auto_pack_registry on {discovered_at}.\n"
        "  Inherits prompts/schema from business_documents_base; analysts\n"
        "  should curate vendor-specific prompts once this pack stabilises.\n"
        "\n"
        "auto_discovered: true\n"
        f"discovered_at: \"{discovered_at}\"\n"
        f"vendor_name: \"{_yaml_escape(vendor_name)}\"\n"
        "inherits_from: business_documents_base"
        f"{doc_hint_line}\n"
        "\n"
        "# Vendor-recognition signals — consulted by content-signal\n"
        "# detection (Wave 1.3 of the uplift) before invoking the LLM\n"
        "# classifier. Analysts should refine these as they review the\n"
        "# pack's first few documents.\n"
        "content_signals:\n"
        "  required_any:\n"
        f"    - \"{_yaml_escape(vendor_name)}\"\n"
    )


def _yaml_escape(s: str) -> str:
    """Escape a vendor name for safe embedding inside a YAML double-quoted scalar."""
    return s.replace("\\", "\\\\").replace("\"", "\\\"")
