"""Routes — process / report / chat / correction / tenant usage + admin onboarding."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from mdi.api.deps import authenticate, current_tenant, db_session, require_admin
from mdi.brain.chat import chat as chat_layer
from mdi.brain.hippocampus import Hippocampus
from mdi.brain.knowledge_graph import KnowledgeGraph
from mdi.kernel.auth import generate_api_key, get_engine
from mdi.kernel.observability import get_logger
from mdi.models.db import (
    Batch,
    CostEvent,
    Tenant,
)
from mdi.models.schemas import ChatRequest, ChatResponse
from mdi.orchestrator.pipeline import run_batch_async

logger = get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# /process
# ---------------------------------------------------------------------------
@router.post("/process")
async def process(
    files: list[UploadFile] = File(...),
    tenant: Tenant = Depends(current_tenant),
) -> dict[str, Any]:
    if not files:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "at least one file required")
    payloads = [
        {"filename": f.filename or "unnamed", "content": (await f.read())}
        for f in files
    ]
    report = await run_batch_async(tenant_id=tenant.id, payloads=payloads)
    return report


# ---------------------------------------------------------------------------
# /report/{batch_id}
# ---------------------------------------------------------------------------
@router.get("/report/{batch_id}")
async def get_report(
    batch_id: uuid.UUID,
    db: AsyncSession = Depends(db_session),
) -> dict[str, Any]:
    row = (await db.execute(select(Batch).where(Batch.id == batch_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "batch not found")
    return dict(row.report or {})


# ---------------------------------------------------------------------------
# /chat
# ---------------------------------------------------------------------------
@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(
    payload: ChatRequest,
    db: AsyncSession = Depends(db_session),
) -> ChatResponse:
    return await chat_layer(kg=KnowledgeGraph(db), request=payload)


# ---------------------------------------------------------------------------
# /correction
# ---------------------------------------------------------------------------
class CorrectionPayload(BaseModel):
    industry: str
    vendor: str
    doc_type: str
    field_path: str
    extracted_value: str | None = None
    corrected_value: str
    note: str = ""


@router.post("/correction")
async def post_correction(
    payload: CorrectionPayload,
    tenant: Tenant = Depends(current_tenant),
    db: AsyncSession = Depends(db_session),
) -> dict[str, Any]:
    hippo = Hippocampus(use_real_embeddings=False)
    cid = await hippo.record_correction(
        db,
        tenant.id,
        industry=payload.industry,
        vendor=payload.vendor,
        doc_type=payload.doc_type,
        field_path=payload.field_path,
        extracted_value=payload.extracted_value,
        corrected_value=payload.corrected_value,
        note=payload.note,
    )
    await db.commit()
    return {"correction_id": str(cid)}


# ---------------------------------------------------------------------------
# /tenant/usage
# ---------------------------------------------------------------------------
@router.get("/tenant/usage")
async def usage(
    tenant: Tenant = Depends(current_tenant),
    db: AsyncSession = Depends(db_session),
) -> dict[str, Any]:
    rows = (
        await db.execute(select(CostEvent).where(CostEvent.tenant_id == tenant.id))
    ).scalars().all()
    spent = sum(r.cost_usd for r in rows)
    return {
        "tenant_id": str(tenant.id),
        "monthly_cap_usd": tenant.monthly_cost_cap_usd,
        "spent_usd": round(spent, 4),
        "events": len(rows),
        "soft_warn_at_usd": round(tenant.monthly_cost_cap_usd * 0.8, 4),
        "hard_cap_at_usd": tenant.monthly_cost_cap_usd,
        "override_active": tenant.cost_override_active,
    }


# ---------------------------------------------------------------------------
# /merges — entity-resolution proposals (per-tenant; uses analyst auth)
# ---------------------------------------------------------------------------
@router.get("/merges")
async def list_merge_proposals(
    status_filter: str = "pending",
    db: AsyncSession = Depends(db_session),
) -> dict[str, Any]:
    """List entity-merge proposals for the current tenant.

    `status_filter` defaults to 'pending'; pass 'all' to see history.
    """
    if status_filter == "all":
        rows = (await db.execute(text(
            "SELECT id::text, node_type, proposed_key, matched_key, score, "
            "       status, decided_by, decided_at, created_at "
            "FROM entity_merge_proposals ORDER BY created_at DESC"
        ))).all()
    else:
        rows = (await db.execute(text(
            "SELECT id::text, node_type, proposed_key, matched_key, score, "
            "       status, decided_by, decided_at, created_at "
            "FROM entity_merge_proposals WHERE status = :s "
            "ORDER BY created_at DESC"
        ), {"s": status_filter})).all()
    return {
        "proposals": [
            {
                "id": r[0], "node_type": r[1], "proposed_key": r[2],
                "matched_key": r[3], "score": r[4], "status": r[5],
                "decided_by": r[6],
                "decided_at": str(r[7]) if r[7] else None,
                "created_at": str(r[8]),
            }
            for r in rows
        ]
    }


class MergeDecision(BaseModel):
    decided_by: str = Field(default="analyst", min_length=1, max_length=255)


@router.post("/merges/{proposal_id}/approve")
async def approve_merge(
    proposal_id: uuid.UUID,
    payload: MergeDecision,
    tenant: Tenant = Depends(current_tenant),
    db: AsyncSession = Depends(db_session),
) -> dict[str, Any]:
    """Approve a pending merge → execute the KG merge → mark approved.

    The mechanical merge: re-point all edges from source → target,
    union aliases, delete source. All inside one transaction.
    """
    from mdi.brain.knowledge_graph import KnowledgeGraph  # local import — avoid cycle
    from mdi.models.db import AuditEvent as _Audit

    proposal_row = (await db.execute(text(
        "SELECT id::text, node_type, proposed_key, matched_key, score, status "
        "FROM entity_merge_proposals WHERE id = :id"
    ), {"id": str(proposal_id)})).first()
    if proposal_row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "proposal not found")
    if proposal_row.status != "pending":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"proposal already {proposal_row.status}",
        )

    kg = KnowledgeGraph(db)
    result = await kg.merge_nodes(
        tenant_id=tenant.id,
        node_type=proposal_row.node_type,
        source_canonical_key=proposal_row.proposed_key,  # the variant
        target_canonical_key=proposal_row.matched_key,   # the keeper
    )
    if not result.get("merged"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"merge could not execute: {result.get('reason')}",
        )

    # Flip the proposal to approved.
    await db.execute(text(
        "UPDATE entity_merge_proposals "
        "SET status = 'approved', decided_by = :who, decided_at = NOW() "
        "WHERE id = :id"
    ), {"who": payload.decided_by, "id": str(proposal_id)})

    # Audit-log the approval for traceability.
    db.add(_Audit(
        tenant_id=tenant.id, actor=payload.decided_by,
        action="entity_resolution.approved", object_type="merge_proposal",
        object_id=str(proposal_id),
        payload={
            "node_type": proposal_row.node_type,
            "source": proposal_row.proposed_key,
            "target": proposal_row.matched_key,
            "score": proposal_row.score,
            **result,
        },
    ))
    await db.commit()
    return {"approved": True, **result}


@router.post("/merges/{proposal_id}/reject")
async def reject_merge(
    proposal_id: uuid.UUID,
    payload: MergeDecision,
    tenant: Tenant = Depends(current_tenant),
    db: AsyncSession = Depends(db_session),
) -> dict[str, Any]:
    """Mark a pending merge as rejected. Future Graph Builder calls won't re-propose."""
    from mdi.models.db import AuditEvent as _Audit

    proposal_row = (await db.execute(text(
        "SELECT id::text, node_type, proposed_key, matched_key, status "
        "FROM entity_merge_proposals WHERE id = :id"
    ), {"id": str(proposal_id)})).first()
    if proposal_row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "proposal not found")
    if proposal_row.status != "pending":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"proposal already {proposal_row.status}",
        )

    await db.execute(text(
        "UPDATE entity_merge_proposals "
        "SET status = 'rejected', decided_by = :who, decided_at = NOW() "
        "WHERE id = :id"
    ), {"who": payload.decided_by, "id": str(proposal_id)})
    db.add(_Audit(
        tenant_id=tenant.id, actor=payload.decided_by,
        action="entity_resolution.rejected", object_type="merge_proposal",
        object_id=str(proposal_id),
        payload={
            "node_type": proposal_row.node_type,
            "source": proposal_row.proposed_key,
            "target": proposal_row.matched_key,
        },
    ))
    await db.commit()
    return {"rejected": True, "id": str(proposal_id)}


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------
@router.get("/health", dependencies=[])
async def health() -> dict[str, str]:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# /architecture — render ARCHITECTURE_OVERVIEW.html for shareable HTTP link
# ---------------------------------------------------------------------------
@router.get("/architecture", response_class=None, dependencies=[])
async def architecture_overview():
    """Serve the architect-handoff HTML doc.

    Looks for `ARCHITECTURE_OVERVIEW.html` next to the repo root. Falls back
    to building from the .md if the HTML is missing (so the endpoint never
    404s as long as the source exists).
    """
    from pathlib import Path

    from fastapi.responses import HTMLResponse, PlainTextResponse

    # mdi/src/mdi/api/routes.py → mdi/  is parents[3]
    root = Path(__file__).resolve().parents[3]
    html_path = root / "ARCHITECTURE_OVERVIEW.html"
    md_path = root / "ARCHITECTURE_OVERVIEW.md"

    if html_path.exists():
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
    if md_path.exists():
        return PlainTextResponse(
            md_path.read_text(encoding="utf-8"),
            media_type="text/markdown",
        )
    raise HTTPException(
        status.HTTP_404_NOT_FOUND,
        "ARCHITECTURE_OVERVIEW not found — run scripts/build_architecture_html.py",
    )


# ===========================================================================
# Admin — tenant onboarding (gated by X-Admin-Key)
# ===========================================================================
class TenantCreatePayload(BaseModel):
    slug: str = Field(min_length=2, max_length=64)
    display_name: str = Field(min_length=1, max_length=255)
    monthly_cost_cap_usd: float = Field(default=200.0, ge=0)
    pack_slug: str | None = None


@router.post("/admin/tenants", dependencies=[Depends(require_admin)])
async def admin_create_tenant(payload: TenantCreatePayload) -> dict[str, Any]:
    """Create a new tenant + issue an initial API key.

    The raw API key is returned ONCE in the response. Persist only its
    hash; the caller is responsible for storing the raw value securely.
    """
    new_tenant_id = uuid.uuid4()
    raw_key, hashed = generate_api_key()
    # Admin path bypasses tenant_session because we're inserting INTO the
    # tenants table, which isn't RLS-protected. Use the engine directly
    # under the mdi_app role.
    engine = get_engine()
    async with engine.begin() as conn:
        # Insert the tenant.
        await conn.execute(
            text(
                "INSERT INTO tenants (id, slug, display_name, monthly_cost_cap_usd, "
                "pack_slug, config) VALUES (:id, :slug, :name, :cap, :pack, '{}'::jsonb)"
            ),
            {
                "id": str(new_tenant_id),
                "slug": payload.slug,
                "name": payload.display_name,
                "cap": payload.monthly_cost_cap_usd,
                "pack": payload.pack_slug,
            },
        )
        # Now set the RLS GUC for the api_keys insert.
        await conn.execute(
            text("SELECT set_config('app.tenant_id', :tid, false)"),
            {"tid": str(new_tenant_id)},
        )
        await conn.execute(
            text(
                "INSERT INTO api_keys (tenant_id, key_hash, label) "
                "VALUES (:tid, :hash, :label)"
            ),
            {"tid": str(new_tenant_id), "hash": hashed, "label": "initial"},
        )
    return {
        "tenant_id": str(new_tenant_id),
        "slug": payload.slug,
        "display_name": payload.display_name,
        "api_key": raw_key,  # SHOWN ONCE — caller must persist
        "monthly_cost_cap_usd": payload.monthly_cost_cap_usd,
    }


@router.get("/admin/embeddings/status", dependencies=[Depends(require_admin)])
async def admin_embeddings_status() -> dict[str, Any]:
    """Current embedder mode + whether the real model is already loaded."""
    from mdi.brain.hippocampus import embedder_status
    return embedder_status()


@router.post("/admin/embeddings/warm", dependencies=[Depends(require_admin)])
async def admin_embeddings_warm() -> dict[str, Any]:
    """Force-load the real bge-m3 model now (vs. lazy on first call).

    Blocks the request for the load duration (~30s on CPU). Use this from
    an admin curl or the Settings tab to pay the cold-start cost up-front
    instead of having the first analyst upload absorb the latency.
    Returns immediately with current status if the model is already loaded.
    """
    import time as _time

    from mdi.brain.hippocampus import _load_real_model, embedder_status

    before = embedder_status()
    if before["loaded"]:
        return {"already_loaded": True, **before}
    t0 = _time.monotonic()
    _load_real_model()  # blocks
    elapsed = int((_time.monotonic() - t0) * 1000)
    return {"already_loaded": False, "loaded_in_ms": elapsed, **embedder_status()}


@router.get("/admin/packs", dependencies=[Depends(require_admin)])
async def admin_list_packs() -> dict[str, Any]:
    """Return the slugs of all packs available on disk.

    Packs live as YAML directories under `src/mdi/packs/`. They're global
    metadata, not per-tenant — the same pack can be assigned to any tenant.
    """
    from mdi.kernel.pack_loader import list_packs  # local import — keep route import light
    return {"packs": list_packs()}


@router.get("/admin/packs/{slug}", dependencies=[Depends(require_admin)])
async def admin_get_pack(slug: str) -> dict[str, Any]:
    """Return the FULLY RESOLVED pack manifest.

    Unlike a raw `skills.yaml` dump, this dereferences every file reference
    (prompts, field schema, validators, etc.) so the caller can render the
    pack's complete contract without additional file-system access.
    """
    from mdi.kernel.pack_loader import PackError, load_pack  # local import
    try:
        pack = load_pack(slug)
    except PackError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e

    # Schema + doc types (always present).
    schema = pack.field_schema()
    doc_types_path = pack.manifest.get("doc_type_taxonomy")
    doc_types: dict[str, Any] = {}
    if doc_types_path:
        try:
            import yaml
            doc_types = yaml.safe_load((pack.root / doc_types_path).read_text(encoding="utf-8")) or {}
        except FileNotFoundError:
            doc_types = {"error": f"file missing: {doc_types_path}"}

    # Resolve every extract_prompts file to inline markdown.
    prompts: dict[str, str] = {}
    for doc_type, _path in (pack.manifest.get("extract_prompts") or {}).items():
        text_or_err = pack.prompt(doc_type)
        prompts[doc_type] = text_or_err

    # Validators — already a list of rule dicts.
    validators = pack.validators()

    # Other YAML files — load each if it exists.
    def _load_yaml(rel: str | None) -> Any:
        if not rel:
            return None
        import yaml
        path = pack.root / rel
        if not path.exists():
            return None
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    merge_rules = _load_yaml(pack.manifest.get("merge_rules"))
    compliance = _load_yaml(pack.manifest.get("compliance", {}).get("business_rules")
                            if isinstance(pack.manifest.get("compliance"), dict) else None)
    enrichment = pack.manifest.get("enrichment", {}) or {}
    enrichment_codes = _load_yaml(enrichment.get("domain_codes") if isinstance(enrichment, dict) else None)
    enrichment_aliases = _load_yaml(enrichment.get("alias_map") if isinstance(enrichment, dict) else None)
    classifier_signals = _load_yaml(
        (pack.manifest.get("classifier", {}) or {}).get("signals")
        if isinstance(pack.manifest.get("classifier"), dict) else None
    )

    return {
        "slug": pack.slug,
        "version": pack.version,
        "description": pack.manifest.get("description", "").strip() or None,
        "field_schema": schema,
        "doc_type_taxonomy": doc_types,
        "extract_prompts": prompts,
        "validators": validators,
        "merge_rules": merge_rules,
        "compliance": compliance,
        "enrichment": {
            "domain_codes": enrichment_codes,
            "alias_map": enrichment_aliases,
        },
        "classifier_signals": classifier_signals,
        "golden_seed_path": pack.manifest.get("golden_seed"),
    }


class TenantUpdatePayload(BaseModel):
    """Mutable tenant fields. Each is optional — only supplied fields update."""
    pack_slug: str | None = None
    monthly_cost_cap_usd: float | None = Field(default=None, ge=0)
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    cost_override_active: bool | None = None


@router.patch(
    "/admin/tenants/{tenant_id}",
    dependencies=[Depends(require_admin)],
)
async def admin_update_tenant(
    tenant_id: uuid.UUID,
    payload: TenantUpdatePayload,
) -> dict[str, Any]:
    """Update mutable tenant fields. Empty payload returns the tenant unchanged.

    Pack assignment is forward-only: existing extractions/patterns under
    open-vocabulary mode stay as they are. New uploads pick up the new
    pack's schema and validators.
    """
    updates: dict[str, Any] = {}
    if payload.pack_slug is not None:
        # Empty string explicitly clears the pack (back to open-vocabulary).
        updates["pack_slug"] = payload.pack_slug or None
        if payload.pack_slug:
            from mdi.kernel.pack_loader import list_packs  # local import
            if payload.pack_slug not in list_packs():
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"unknown pack: {payload.pack_slug!r}",
                )
    if payload.monthly_cost_cap_usd is not None:
        updates["monthly_cost_cap_usd"] = payload.monthly_cost_cap_usd
    if payload.display_name is not None:
        updates["display_name"] = payload.display_name
    if payload.cost_override_active is not None:
        updates["cost_override_active"] = payload.cost_override_active

    engine = get_engine()
    async with engine.begin() as conn:
        if updates:
            set_clauses = ", ".join(f"{k} = :{k}" for k in updates)
            params = {**updates, "id": str(tenant_id)}
            result = await conn.execute(
                text(f"UPDATE tenants SET {set_clauses} WHERE id = :id"),
                params,
            )
            if result.rowcount == 0:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "tenant not found")
        row = (
            await conn.execute(
                text(
                    "SELECT id::text, slug, display_name, monthly_cost_cap_usd, "
                    "pack_slug, cost_override_active FROM tenants WHERE id = :id"
                ),
                {"id": str(tenant_id)},
            )
        ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "tenant not found")
    return {
        "id": row[0], "slug": row[1], "display_name": row[2],
        "monthly_cost_cap_usd": row[3], "pack_slug": row[4],
        "cost_override_active": row[5],
    }


@router.get("/admin/tenants", dependencies=[Depends(require_admin)])
async def admin_list_tenants() -> dict[str, Any]:
    engine = get_engine()
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT id::text, slug, display_name, monthly_cost_cap_usd, "
                    "pack_slug, created_at FROM tenants ORDER BY created_at DESC"
                )
            )
        ).all()
    return {
        "tenants": [
            {
                "id": r[0], "slug": r[1], "display_name": r[2],
                "monthly_cost_cap_usd": r[3], "pack_slug": r[4],
                "created_at": str(r[5]),
            }
            for r in rows
        ]
    }


class ApiKeyPayload(BaseModel):
    label: str = Field(default="rotation", min_length=1, max_length=128)


@router.post(
    "/admin/tenants/{tenant_id}/api_keys",
    dependencies=[Depends(require_admin)],
)
async def admin_issue_api_key(
    tenant_id: uuid.UUID, payload: ApiKeyPayload,
) -> dict[str, Any]:
    """Issue a new API key for an existing tenant. Returned ONCE."""
    raw_key, hashed = generate_api_key()
    engine = get_engine()
    async with engine.begin() as conn:
        # Verify tenant exists.
        exists = (
            await conn.execute(
                text("SELECT 1 FROM tenants WHERE id = :tid"),
                {"tid": str(tenant_id)},
            )
        ).first()
        if exists is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "tenant not found")
        # Set RLS GUC for the api_keys insert.
        await conn.execute(
            text("SELECT set_config('app.tenant_id', :tid, false)"),
            {"tid": str(tenant_id)},
        )
        await conn.execute(
            text(
                "INSERT INTO api_keys (tenant_id, key_hash, label) "
                "VALUES (:tid, :hash, :label)"
            ),
            {"tid": str(tenant_id), "hash": hashed, "label": payload.label},
        )
    return {
        "tenant_id": str(tenant_id),
        "label": payload.label,
        "api_key": raw_key,  # SHOWN ONCE
    }



# ---------------------------------------------------------------------------
# Auto-pack proposals queue (Wave 1.2 of the DD uplift)
# ---------------------------------------------------------------------------
@router.get("/admin/auto-packs", dependencies=[Depends(require_admin)])
async def admin_list_auto_packs(
    status_filter: str = "pending",
    tenant: Tenant = Depends(current_tenant),
    db: AsyncSession = Depends(db_session),
) -> dict[str, Any]:
    """List auto-discovered pack proposals.

    `status_filter` defaults to `pending`; accepted values are
    pending / approved / rejected / superseded / all.
    """
    from mdi.kernel.auto_pack_registry import list_proposals
    _ = tenant  # RLS scopes the query — tenant FK is enforced by app.tenant_id GUC
    return {"proposals": await list_proposals(db, status_filter=status_filter)}


class AutoPackDecision(BaseModel):
    decided_by: str = Field(default="analyst", min_length=1, max_length=255)


@router.post(
    "/admin/auto-packs/{proposal_id}/promote",
    dependencies=[Depends(require_admin)],
)
async def admin_promote_auto_pack(
    proposal_id: uuid.UUID,
    payload: AutoPackDecision,
    tenant: Tenant = Depends(current_tenant),
    db: AsyncSession = Depends(db_session),
) -> dict[str, Any]:
    """One-click promote: writes packs/_auto/<slug>/skills.yaml and
    flips the proposal to approved. Idempotent — re-promoting an already-
    approved proposal returns 409 rather than re-writing the file."""
    from pathlib import Path

    from mdi.kernel.auto_pack_registry import promote_proposal
    from mdi.models.db import AuditEvent as _Audit

    packs_root = Path(__file__).resolve().parents[1] / "packs"
    result = await promote_proposal(
        db,
        proposal_id=proposal_id,
        decided_by=payload.decided_by,
        packs_root=packs_root,
    )
    if not result.get("promoted"):
        reason = result.get("reason", "unknown")
        if reason == "not_found":
            raise HTTPException(status.HTTP_404_NOT_FOUND, "proposal not found")
        raise HTTPException(status.HTTP_409_CONFLICT, f"cannot promote: {reason}")

    db.add(_Audit(
        tenant_id=tenant.id, actor=payload.decided_by,
        action="auto_pack.promoted", object_type="auto_pack_proposal",
        object_id=str(proposal_id),
        payload=result,
    ))
    await db.commit()
    return result


@router.post(
    "/admin/auto-packs/{proposal_id}/reject",
    dependencies=[Depends(require_admin)],
)
async def admin_reject_auto_pack(
    proposal_id: uuid.UUID,
    payload: AutoPackDecision,
    tenant: Tenant = Depends(current_tenant),
    db: AsyncSession = Depends(db_session),
) -> dict[str, Any]:
    """Mark a proposal rejected — same shape as merge rejection."""
    from mdi.kernel.auto_pack_registry import reject_proposal
    from mdi.models.db import AuditEvent as _Audit

    result = await reject_proposal(
        db, proposal_id=proposal_id, decided_by=payload.decided_by,
    )
    if not result.get("rejected"):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"proposal not found or not pending: {result.get('reason')}",
        )
    db.add(_Audit(
        tenant_id=tenant.id, actor=payload.decided_by,
        action="auto_pack.rejected", object_type="auto_pack_proposal",
        object_id=str(proposal_id),
        payload={},
    ))
    await db.commit()
    return result


# ---------------------------------------------------------------------------
# Spend ledger (Wave 1.4 of the DD uplift)
# ---------------------------------------------------------------------------
@router.get("/admin/spend", dependencies=[Depends(require_admin)])
async def admin_spend_snapshot() -> dict[str, Any]:
    """Cumulative LLM spend across process restarts, broken out by backend.

    This is independent of the daily CostTracker (which lives in-process
    and resets every restart) — useful for "what did this deployment
    cost so far?" reporting and capped-trial enforcement.
    """
    from mdi.kernel.settings import get_settings
    from mdi.kernel.spend_ledger import snapshot as _spend_snapshot

    data = _spend_snapshot()
    s = get_settings()
    return {
        "total_usd": data.get("total_usd", 0.0),
        "by_backend": data.get("by_backend", {}),
        "cumulative_cap_usd": s.cumulative_spend_cap_usd,
        "cap_enabled": s.cumulative_spend_cap_usd > 0,
    }


_ = authenticate
