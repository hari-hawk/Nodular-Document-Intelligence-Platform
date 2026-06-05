"""Routes — process / report / chat / correction / tenant usage + admin onboarding."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile, status
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
# /batches — list recent batches (Wave 3.2; admin-or-tenant auth)
# ---------------------------------------------------------------------------
@router.get("/batches")
async def list_batches(
    limit: int = 20,
    tenant_id_filter: str | None = None,
    # Accept either tenant API key (default UI path) OR admin key.
    # We resolve each via header by hand here rather than via
    # Depends() so a missing tenant key falls through to admin check
    # instead of 401-ing the request.
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """List recent batches. Two auth paths:

    1. Tenant auth (X-API-Key or Authorization: Bearer): RLS-scoped to
       that tenant, returns their batches only.
    2. Admin auth (X-Admin-Key): lists batches across ALL tenants. Each
       row includes tenant_id so the UI can show which tenant a batch
       belongs to. Optional `?tenant_id=` filters to a single tenant.

    This dual-auth shape exists because the Workspace page is
    reachable both by analysts signed in to one tenant AND by
    platform admins exploring the install. The single-auth design
    surprised users who'd signed in with only the admin key.
    """
    from mdi.api.deps import authenticate as _auth_tenant
    from mdi.api.deps import require_admin as _require_admin

    # Try tenant auth first; if no tenant key/JWT given, fall back to
    # admin auth. If neither succeeds, surface a friendly 401.
    tenant_uuid: uuid.UUID | None = None
    is_admin = False
    if x_api_key or (authorization and authorization.lower().startswith("bearer ")):
        tenant_uuid = await _auth_tenant(
            authorization=authorization, x_api_key=x_api_key,
        )
    elif x_admin_key:
        await _require_admin(x_admin_key=x_admin_key)
        is_admin = True
    else:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "/batches requires either X-API-Key (tenant) or X-Admin-Key (admin)",
        )

    limit = max(1, min(int(limit), 100))

    # Admin path uses the PRIVILEGED engine (settings.database_url_admin_async)
    # which is configured at deploy time to a superuser DSN so RLS doesn't
    # filter — admins see across tenants. Production single-role setups
    # can leave it equal to the app DSN; the cross-tenant query still
    # works because no tenant GUC is set, and the policy on tables that
    # use NULLIF resolves to "all rows" for an unset GUC. The two-engine
    # design lets the dev defaults match this without app-code changes.
    from mdi.kernel.auth import get_admin_engine, tenant_session
    base_select = (
        "SELECT id::text, tenant_id::text, status, total_documents, started_at, finished_at, "
        "       cost_usd, "
        "       LEFT(COALESCE(report->>'narrator_summary', ''), 240) AS narrator_preview, "
        "       COALESCE(jsonb_array_length(report->'anomalies'), 0) AS anomaly_count, "
        "       COALESCE(jsonb_array_length(report->'insights'), 0) AS insight_count "
        "FROM batches "
    )

    if is_admin:
        engine = get_admin_engine()
        async with engine.connect() as conn:
            # Admin can scope to a specific tenant via ?tenant_id=. The
            # query intentionally bypasses RLS via the privileged role.
            if tenant_id_filter:
                rows = (await conn.execute(text(
                    base_select + "WHERE tenant_id = :tid "
                    "ORDER BY started_at DESC LIMIT :limit"
                ), {"tid": tenant_id_filter, "limit": limit})).all()
            else:
                rows = (await conn.execute(text(
                    base_select + "ORDER BY started_at DESC LIMIT :limit"
                ), {"limit": limit})).all()
    else:
        # Tenant path — RLS-scoped via the standard tenant_session path
        # so we get the same isolation as every other tenant endpoint.
        async with tenant_session(tenant_uuid) as db:  # type: ignore[arg-type]
            rows = (await db.execute(text(
                base_select + "ORDER BY started_at DESC LIMIT :limit"
            ), {"limit": limit})).all()

    return {
        "auth_mode": "admin" if is_admin else "tenant",
        "batches": [
            {
                "id": r[0],
                "tenant_id": r[1],
                "status": r[2],
                "total_documents": r[3],
                "started_at": str(r[4]) if r[4] else None,
                "finished_at": str(r[5]) if r[5] else None,
                "cost_usd": float(r[6] or 0.0),
                "narrator_preview": r[7] or "",
                "anomaly_count": int(r[8] or 0),
                "insight_count": int(r[9] or 0),
            }
            for r in rows
        ],
    }


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
    # Wave 2.3 — embed the correction immediately so the next document
    # from a similar context can be hinted via semantic recall. Failure
    # here is non-fatal: the exact-match path still works without an
    # embedding, and a backfill job re-embeds older corrections.
    try:
        await hippo.embed_correction(
            db, tenant.id,
            correction_id=cid,
            industry=payload.industry, vendor=payload.vendor,
            doc_type=payload.doc_type, field_path=payload.field_path,
            extracted_value=payload.extracted_value,
            corrected_value=payload.corrected_value,
        )
    except Exception as e:
        logger.warning("correction.embed_failed", correction_id=str(cid), error=str(e))
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
async def _resolve_admin_or_tenant(
    x_api_key: str | None,
    x_admin_key: str | None,
    authorization: str | None,
) -> tuple[uuid.UUID | None, bool]:
    """Helper for endpoints that accept EITHER tenant or admin auth.

    Returns (tenant_uuid_or_None, is_admin). Raises 401 only when
    NEITHER auth header is supplied. Used by /admin/patterns,
    /admin/tenant-facts, /admin/auto-packs — all surfaces an admin
    user reasonably wants to browse across tenants.
    """
    from mdi.api.deps import authenticate as _auth_tenant
    from mdi.api.deps import require_admin as _require_admin

    if x_api_key or (authorization and authorization.lower().startswith("bearer ")):
        tenant_uuid = await _auth_tenant(
            authorization=authorization, x_api_key=x_api_key,
        )
        return tenant_uuid, False
    if x_admin_key:
        await _require_admin(x_admin_key=x_admin_key)
        return None, True
    raise HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "endpoint requires either X-API-Key (tenant) or X-Admin-Key (admin)",
    )


@router.get("/admin/auto-packs")
async def admin_list_auto_packs(
    status_filter: str = "pending",
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """List auto-discovered pack proposals — admin OR tenant auth.

    Admin mode lists across all tenants; tenant mode is RLS-scoped.
    Each proposal carries a `tenant_id` in admin mode so the UI can
    show which tenant a vendor was discovered for.

    `status_filter` defaults to `pending`; accepted values are
    pending / approved / rejected / superseded / all.
    """
    from mdi.kernel.auth import get_admin_engine, tenant_session
    tenant_uuid, is_admin = await _resolve_admin_or_tenant(
        x_api_key, x_admin_key, authorization,
    )
    base_select = (
        "SELECT id::text, tenant_id::text, vendor_slug, vendor_name, "
        "       doc_type_hint, sighting_count, status, decided_by, "
        "       decided_at, promoted_path, created_at, last_seen_at "
        "FROM auto_pack_proposals "
    )
    where = "WHERE status = :s " if status_filter != "all" else ""
    params: dict[str, Any] = {}
    if status_filter != "all":
        params["s"] = status_filter

    if is_admin:
        engine = get_admin_engine()
        async with engine.connect() as conn:
            rows = (await conn.execute(text(
                base_select + where + "ORDER BY sighting_count DESC, created_at DESC"
            ), params)).all()
    else:
        async with tenant_session(tenant_uuid) as db:  # type: ignore[arg-type]
            rows = (await db.execute(text(
                base_select + where + "ORDER BY sighting_count DESC, created_at DESC"
            ), params)).all()

    return {
        "auth_mode": "admin" if is_admin else "tenant",
        "proposals": [
            {
                "id": r[0], "tenant_id": r[1], "vendor_slug": r[2],
                "vendor_name": r[3], "doc_type_hint": r[4],
                "sighting_count": int(r[5] or 0),
                "status": r[6], "decided_by": r[7],
                "decided_at": str(r[8]) if r[8] else None,
                "promoted_path": r[9],
                "created_at": str(r[10]) if r[10] else None,
                "last_seen_at": str(r[11]) if r[11] else None,
            }
            for r in rows
        ],
    }


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
# Patterns explorer — what the brain has memorised (Wave 3.3)
# ---------------------------------------------------------------------------
@router.get("/admin/patterns")
async def admin_list_patterns(
    industry: str | None = None,
    limit: int = 100,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """List Hippocampus patterns — admin OR tenant auth.

    Tenant mode: RLS-scoped, returns this tenant's patterns.
    Admin mode: across all tenants; each row carries tenant_id.
    """
    from mdi.kernel.auth import get_admin_engine, tenant_session
    tenant_uuid, is_admin = await _resolve_admin_or_tenant(
        x_api_key, x_admin_key, authorization,
    )
    limit = max(1, min(int(limit), 500))
    base = (
        "SELECT id::text, tenant_id::text, industry, vendor, doc_type, "
        "       seen_count, last_seen_at, created_at, "
        "       jsonb_array_length(schema_def->'fields') AS field_count, "
        "       jsonb_array_length(rules->'rules') AS rule_count "
        "FROM patterns "
    )
    where = "WHERE industry = :ind " if industry else ""
    params: dict[str, Any] = {"limit": limit}
    if industry:
        params["ind"] = industry

    if is_admin:
        engine = get_admin_engine()
        async with engine.connect() as conn:
            rows = (await conn.execute(text(
                base + where + "ORDER BY seen_count DESC, last_seen_at DESC LIMIT :limit"
            ), params)).all()
    else:
        async with tenant_session(tenant_uuid) as db:  # type: ignore[arg-type]
            rows = (await db.execute(text(
                base + where + "ORDER BY seen_count DESC, last_seen_at DESC LIMIT :limit"
            ), params)).all()

    return {
        "auth_mode": "admin" if is_admin else "tenant",
        "patterns": [
            {
                "id": r[0], "tenant_id": r[1],
                "industry": r[2], "vendor": r[3], "doc_type": r[4],
                "seen_count": int(r[5] or 0),
                "last_seen_at": str(r[6]) if r[6] else None,
                "created_at": str(r[7]) if r[7] else None,
                "field_count": int(r[8] or 0),
                "rule_count": int(r[9] or 0),
            }
            for r in rows
        ],
    }


@router.get("/admin/patterns/{pattern_id}")
async def admin_get_pattern(
    pattern_id: uuid.UUID,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Full pattern detail — schema fields + rules. Admin OR tenant auth."""
    from mdi.kernel.auth import get_admin_engine, tenant_session
    tenant_uuid, is_admin = await _resolve_admin_or_tenant(
        x_api_key, x_admin_key, authorization,
    )
    q = (
        "SELECT id::text, tenant_id::text, industry, vendor, doc_type, "
        "       schema_def, rules, seen_count, last_seen_at, created_at "
        "FROM patterns WHERE id = :id"
    )
    if is_admin:
        engine = get_admin_engine()
        async with engine.connect() as conn:
            row = (await conn.execute(text(q), {"id": str(pattern_id)})).first()
    else:
        async with tenant_session(tenant_uuid) as db:  # type: ignore[arg-type]
            row = (await db.execute(text(q), {"id": str(pattern_id)})).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "pattern not found")
    return {
        "id": row[0], "tenant_id": row[1],
        "industry": row[2], "vendor": row[3], "doc_type": row[4],
        "schema_def": row[5] or {},
        "rules": row[6] or {},
        "seen_count": int(row[7] or 0),
        "last_seen_at": str(row[8]) if row[8] else None,
        "created_at": str(row[9]) if row[9] else None,
    }


# ---------------------------------------------------------------------------
# Handler registry — code-bridge for patterns + commands (Wave 2.5)
# ---------------------------------------------------------------------------
@router.get("/admin/handlers", dependencies=[Depends(require_admin)])
async def admin_list_handlers() -> dict[str, Any]:
    """Manifest of all registered Python handlers in this process.

    Patterns and natural-language commands reference handlers by
    `handler_id`. This endpoint is the public allow-list — the LLM
    dispatcher reads it to know what it can invoke.
    """
    from mdi.handlers import list_handlers
    return {"handlers": list_handlers()}


class RunHandlerPayload(BaseModel):
    document_id: uuid.UUID | None = None
    kwargs: dict[str, Any] = Field(default_factory=dict)


@router.post(
    "/admin/handlers/{handler_id}/run",
    dependencies=[Depends(require_admin)],
)
async def admin_run_handler(
    handler_id: str,
    payload: RunHandlerPayload,
    tenant: Tenant = Depends(current_tenant),
    db: AsyncSession = Depends(db_session),
) -> dict[str, Any]:
    """Execute a registered handler against the current tenant context.

    The handler runs with whatever document context the caller supplies
    (we hydrate the extraction + cluster from the DB if document_id is
    set). Returns the HandlerResult shape — `ok`, `output`, `data`,
    `side_effects` — so the caller can render it directly.
    """
    from mdi.handlers import HandlerContext, run_handler

    extraction_dict: dict[str, Any] = {}
    cluster_dict: dict[str, Any] = {}
    if payload.document_id is not None:
        row = (await db.execute(text(
            "SELECT d.cluster, e.fields "
            "FROM documents d LEFT JOIN extractions e ON e.document_id = d.id "
            "WHERE d.id = :id"
        ), {"id": str(payload.document_id)})).first()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
        cluster_dict = row[0] or {}
        extraction_dict = row[1] or {}

    ctx = HandlerContext(
        tenant_id=tenant.id,
        document_id=payload.document_id,
        extraction=extraction_dict,
        cluster=cluster_dict,
        kwargs=payload.kwargs,
    )
    result = await run_handler(handler_id, ctx)
    return {
        "ok": result.ok,
        "output": result.output,
        "data": result.data,
        "side_effects": result.side_effects,
    }


# ---------------------------------------------------------------------------
# Tenant facts — per-tenant master-data store (Wave 2.4)
# ---------------------------------------------------------------------------
@router.get("/admin/tenant-facts")
async def admin_list_tenant_facts(
    fact_type: str | None = None,
    limit: int = 500,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """List tenant facts — admin OR tenant auth.

    Tenant mode: RLS-scoped to this tenant.
    Admin mode: cross-tenant; each row includes tenant_id.
    """
    from mdi.kernel.auth import get_admin_engine, tenant_session
    tenant_uuid, is_admin = await _resolve_admin_or_tenant(
        x_api_key, x_admin_key, authorization,
    )
    limit = max(1, min(int(limit), 5000))
    base = (
        "SELECT id::text, tenant_id::text, fact_type, key, value, confidence, "
        "       source_doc_id::text, sighting_count, last_seen_at, created_at "
        "FROM tenant_facts "
    )
    where = "WHERE fact_type = :ft " if fact_type else ""
    params: dict[str, Any] = {"limit": limit}
    if fact_type:
        params["ft"] = fact_type
    order = "ORDER BY confidence DESC, sighting_count DESC, last_seen_at DESC LIMIT :limit"

    if is_admin:
        engine = get_admin_engine()
        async with engine.connect() as conn:
            rows = (await conn.execute(text(base + where + order), params)).all()
    else:
        async with tenant_session(tenant_uuid) as db:  # type: ignore[arg-type]
            rows = (await db.execute(text(base + where + order), params)).all()

    return {
        "auth_mode": "admin" if is_admin else "tenant",
        "facts": [
            {
                "id": r[0], "tenant_id": r[1], "fact_type": r[2],
                "key": r[3], "value": r[4],
                "confidence": float(r[5] or 0.0),
                "source_doc_id": r[6],
                "sighting_count": int(r[7] or 0),
                "last_seen_at": str(r[8]) if r[8] else None,
                "created_at": str(r[9]) if r[9] else None,
            }
            for r in rows
        ],
    }


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
