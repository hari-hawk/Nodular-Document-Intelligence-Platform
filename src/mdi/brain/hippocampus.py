"""Hippocampus — pattern + correction memory (Stages 3, 6, 9).

* Stage 3 — given a Cluster, look up a similar pattern via pgvector cosine
  similarity. Hit short-circuits Pattern Cortex (Stage 4) and Conscience
  invent (Stage 5).
* Stage 6 — given (industry, vendor, doc_type), pull active corrections.
* Stage 9 — write back the pattern (with embedding) and observed agreement
  bumps for matched corrections.

Embedding strategy: BAAI/bge-m3 in-process. The model is heavy (~2GB);
we lazy-load and cache. For tests the Hippocampus is constructed with
`use_embeddings=False`, falling back to a deterministic stub embedder.
"""
from __future__ import annotations

import hashlib
import math
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mdi.kernel.observability import get_logger
from mdi.kernel.settings import get_settings
from mdi.models.db import Correction as CorrectionRow
from mdi.models.db import Pattern as PatternRow
from mdi.models.schemas import (
    Cluster,
    CorrectionHint,
    MemoryHit,
    Rule,
    RuleSet,
    Schema,
)

logger = get_logger(__name__)

EMBED_DIM = 1024  # bge-m3
SIMILARITY_THRESHOLD = 0.82  # below this we treat as a miss


# ---------------------------------------------------------------------------
# Embedding adapter
# ---------------------------------------------------------------------------
#
# The real bge-m3 model is ~2GB on disk and takes ~30s to load. We hold it
# at module level so multiple Hippocampus instances share one loaded copy.
# `_load_real_model()` is idempotent; concurrent callers see the same object.
# ---------------------------------------------------------------------------
_REAL_MODEL: Any | None = None
_REAL_MODEL_LOADING: bool = False


def _load_real_model() -> Any:
    """Idempotently load (and cache) the bge-m3 model. Heavy — call once."""
    global _REAL_MODEL, _REAL_MODEL_LOADING
    if _REAL_MODEL is not None:
        return _REAL_MODEL
    _REAL_MODEL_LOADING = True
    try:
        from sentence_transformers import SentenceTransformer  # heavy import

        s = get_settings()
        logger.info("embedder.loading", model=s.embed_model, device=s.embed_device)
        _REAL_MODEL = SentenceTransformer(s.embed_model, device=s.embed_device)
        logger.info("embedder.loaded", model=s.embed_model)
        return _REAL_MODEL
    finally:
        _REAL_MODEL_LOADING = False


def embedder_status() -> dict[str, Any]:
    """Snapshot used by the UI sidebar + Settings tab."""
    s = get_settings()
    return {
        "mode": "real" if s.use_real_embeddings else "stub",
        "model": s.embed_model,
        "device": s.embed_device,
        "loaded": _REAL_MODEL is not None,
        "loading": _REAL_MODEL_LOADING,
    }


class _Embedder:
    """Embedding wrapper. Real model is module-level singleton; stub is per-call.

    When `use_real_model=True`, the first call may block for ~30s while bge-m3
    downloads/loads. Subsequent calls reuse the cached model (~50ms/encode on CPU).
    When `use_real_model=False`, we use a deterministic SHA-based pseudo-embedding
    — instant, but no semantic similarity (identical-input only).
    """

    def __init__(self, *, use_real_model: bool | None = None) -> None:
        # None means "read from settings" so callers don't have to thread it.
        if use_real_model is None:
            use_real_model = get_settings().use_real_embeddings
        self.use_real_model = use_real_model

    def embed(self, text: str) -> list[float]:
        if self.use_real_model:
            model = _load_real_model()
            vec = model.encode([text], normalize_embeddings=True)[0]
            return [float(x) for x in vec]
        return _stub_embedding(text)


def _stub_embedding(text: str) -> list[float]:
    """Deterministic 1024-d unit vector seeded from text. Good enough for tests."""
    seed = hashlib.sha256(text.encode("utf-8")).digest()
    raw: list[float] = []
    for i in range(EMBED_DIM):
        b = seed[i % len(seed)]
        raw.append(((b - 128) / 128.0) + (i % 7) * 0.001)
    norm = math.sqrt(sum(v * v for v in raw))
    return [v / norm for v in raw]


# ---------------------------------------------------------------------------
# Hippocampus
# ---------------------------------------------------------------------------
class Hippocampus:
    def __init__(self, *, use_real_embeddings: bool | None = None) -> None:
        # `None` defers to settings.use_real_embeddings (the production toggle).
        # Callers that want to force a mode (tests, opt-in benchmarks) pass
        # an explicit bool.
        self.embedder = _Embedder(use_real_model=use_real_embeddings)

    @staticmethod
    def cluster_text(c: Cluster) -> str:
        return f"{c.industry} | {c.vendor} | {c.doc_type} | layout={c.layout}"

    def embed(self, c: Cluster) -> list[float]:
        return self.embedder.embed(self.cluster_text(c))

    async def lookup_pattern(
        self, db: AsyncSession, tenant_id: uuid.UUID, cluster: Cluster
    ) -> MemoryHit | None:
        emb = self.embed(cluster)
        # asyncpg can't bind a Python list directly to a pgvector parameter,
        # so we serialise to the pgvector text literal "[v1,v2,...]". The
        # explicit CAST in the SQL parses it server-side.
        emb_literal = "[" + ",".join(format(x, ".7f") for x in emb) + "]"
        from sqlalchemy import text

        # IMPORTANT: we filter on (industry, doc_type) only — NOT on vendor.
        # Eyes' vendor naming is non-deterministic across calls (Gemini may
        # call the same issuer "AT&T" or "AT&T Business Services"), so an
        # exact-vendor filter would force a forever-cold cache. The vendor
        # is encoded in the embedding (cluster_text includes it), and the
        # SIMILARITY_THRESHOLD (0.82) keeps genuinely different vendors apart.
        row = (
            await db.execute(
                text(
                    """
                    SELECT id, schema_def, rules, 1 - (embedding <=> CAST(:vec AS vector)) AS sim
                    FROM patterns
                    WHERE industry = :industry
                      AND doc_type = :doc_type
                      AND embedding IS NOT NULL
                    ORDER BY embedding <=> CAST(:vec AS vector)
                    LIMIT 1
                    """
                ),
                {
                    "vec": emb_literal,
                    "industry": cluster.industry,
                    "doc_type": cluster.doc_type,
                },
            )
        ).first()

        if row is None or row.sim < SIMILARITY_THRESHOLD:
            return None

        schema = Schema.model_validate(row.schema_def or {"fields": [], "discovered_from": "memory"})
        rules_payload = row.rules or {"rules": []}
        rules = RuleSet.model_validate(rules_payload)
        return MemoryHit.model_validate(
            {
                "pattern_id": row.id,
                "similarity": float(row.sim),
                "schema": schema,
                "rules": rules,
            }
        )

    async def lookup_patterns_multi(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        cluster: Cluster,
        *,
        top_k: int = 5,
        min_similarity: float = 0.50,
    ) -> list[MemoryHit]:
        """Return the top-K patterns whose cluster-text embedding is
        close to `cluster`'s, sorted by similarity DESC.

        Wave 2.1 of the DD uplift — multi-pattern recognition. A single
        document can legitimately resemble several stored patterns at
        once (an invoice with a contract amendment attached, a
        consolidated bill spanning two vendors). `lookup_pattern` keeps
        the simple "give me the winner" contract for code paths that
        only need the top hit; this is the surface for code paths that
        want the full ranked set.

        `min_similarity` defaults LOWER than SIMILARITY_THRESHOLD (0.50
        vs 0.82) because the caller usually wants to SEE the field of
        candidates including the weak ones — the orchestrator filters
        upward at the use site. Returning weak matches here is the
        right default for a "show me everything that looks even a
        little like this" query.
        """
        emb = self.embed(cluster)
        emb_literal = "[" + ",".join(format(x, ".7f") for x in emb) + "]"
        from sqlalchemy import text

        rows = (
            await db.execute(
                text(
                    """
                    SELECT id, schema_def, rules,
                           1 - (embedding <=> CAST(:vec AS vector)) AS sim
                    FROM patterns
                    WHERE industry = :industry
                      AND doc_type = :doc_type
                      AND embedding IS NOT NULL
                    ORDER BY embedding <=> CAST(:vec AS vector)
                    LIMIT :limit
                    """
                ),
                {
                    "vec": emb_literal,
                    "industry": cluster.industry,
                    "doc_type": cluster.doc_type,
                    "limit": int(top_k),
                },
            )
        ).all()

        hits: list[MemoryHit] = []
        for row in rows:
            if row.sim < min_similarity:
                continue
            schema = Schema.model_validate(
                row.schema_def or {"fields": [], "discovered_from": "memory"}
            )
            rules = RuleSet.model_validate(row.rules or {"rules": []})
            hits.append(MemoryHit.model_validate({
                "pattern_id": row.id,
                "similarity": float(row.sim),
                "schema": schema,
                "rules": rules,
            }))
        return hits

    async def get_corrections(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        cluster: Cluster,
    ) -> list[CorrectionHint]:
        rows = (
            await db.execute(
                select(CorrectionRow).where(
                    CorrectionRow.industry == cluster.industry,
                    CorrectionRow.vendor == cluster.vendor,
                    CorrectionRow.doc_type == cluster.doc_type,
                )
            )
        ).scalars().all()
        return [
            CorrectionHint(
                field_path=r.field_path,
                extracted_value=r.extracted_value,
                corrected_value=r.corrected_value,
                note=r.note or "",
                agreement_count=r.agreement_count,
            )
            for r in rows
        ]

    async def write_pattern(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        cluster: Cluster,
        schema: Schema,
        rules: RuleSet,
        pattern_id: uuid.UUID | None = None,
    ) -> uuid.UUID:
        """UPSERT on (tenant_id, industry, vendor, doc_type).

        After migration 0003, the same scope can only appear once per tenant.
        On conflict we bump seen_count and refresh the embedding + schema +
        rules so the pattern stays current with the most recent observation.
        """
        from sqlalchemy import func
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        emb = self.embed(cluster)
        stmt = (
            pg_insert(PatternRow.__table__)
            .values(
                tenant_id=tenant_id,
                industry=cluster.industry,
                vendor=cluster.vendor,
                doc_type=cluster.doc_type,
                schema_def=schema.model_dump(),
                rules=rules.model_dump(),
                embedding=emb,
                seen_count=1,
            )
            .on_conflict_do_update(
                constraint="uq_patterns_scope",
                set_={
                    "schema_def": schema.model_dump(),
                    "rules": rules.model_dump(),
                    "embedding": emb,
                    "seen_count": PatternRow.__table__.c.seen_count + 1,
                    "last_seen_at": func.now(),
                },
            )
            .returning(PatternRow.__table__.c.id)
        )
        row = (await db.execute(stmt)).first()
        assert row is not None
        return row.id  # type: ignore[no-any-return]

    async def record_correction(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        industry: str,
        vendor: str,
        doc_type: str,
        field_path: str,
        extracted_value: str | None,
        corrected_value: str,
        note: str = "",
    ) -> uuid.UUID:
        existing = (
            await db.execute(
                select(CorrectionRow).where(
                    CorrectionRow.industry == industry,
                    CorrectionRow.vendor == vendor,
                    CorrectionRow.doc_type == doc_type,
                    CorrectionRow.field_path == field_path,
                    CorrectionRow.corrected_value == corrected_value,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.agreement_count += 1
            await db.flush()
            return existing.id
        new = CorrectionRow(
            tenant_id=tenant_id,
            industry=industry,
            vendor=vendor,
            doc_type=doc_type,
            field_path=field_path,
            extracted_value=extracted_value,
            corrected_value=corrected_value,
            note=note,
        )
        db.add(new)
        await db.flush()
        return new.id


def baseline_rules_from_schema(schema: Schema) -> RuleSet:
    """Conservative type-derived rules. Always-on; safer than invented rules."""
    rules: list[Rule] = []
    for f in schema.fields:
        if f.required:
            rules.append(
                Rule(
                    rule_id=f"required_{f.name}",
                    expression=f"fields.get('{f.name}') is not None",
                    severity="HIGH",
                    message=f"missing required field {f.name}",
                )
            )
        if f.type == "currency":
            rules.append(
                Rule(
                    rule_id=f"currency_nonneg_{f.name}",
                    expression=f"(fields.get('{f.name}') or 0) >= 0",
                    severity="MEDIUM",
                    message=f"{f.name} must be non-negative",
                )
            )
        if f.type == "date":
            # Avoid isinstance() — not in the simpleeval whitelist. str(...)
            # coerces None / numeric values; len >= 8 covers ISO 8601 dates
            # ("YYYY-MM-DD" minimum).
            rules.append(
                Rule(
                    rule_id=f"date_iso_{f.name}",
                    expression=(
                        f"fields.get('{f.name}') is None "
                        f"or len(str(fields.get('{f.name}'))) >= 8"
                    ),
                    severity="LOW",
                    message=f"{f.name} should be ISO-formatted",
                )
            )
    return RuleSet(rules=rules)
