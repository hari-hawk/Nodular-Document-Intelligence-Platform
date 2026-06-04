# MDI · Pipeline and Framework Guide

How the platform processes a document, what makes it generic, and how to
reuse it across projects without forking the codebase.

This is the "zoom out and see the whole shape" doc. For step-by-step
setup, see `README.md`. For locked architectural decisions, see
`CLAUDE.md`. For what's still missing, see `GAP_ANALYSIS.md`. For
consuming MDI from another codebase, see `MODULE_GUIDE.md`.

---

## 1. The one-paragraph summary

MDI is an **autonomous document-intelligence brain** sitting on a
**multi-tenant Postgres + pgvector chassis**. A document goes in; a
structured, validated, classified, knowledge-graph-enriched
`BatchReport` comes out. The same engine handles invoices, claims,
contracts, statements, and receipts across telecom, healthcare, cloud
finance, legal, and manufacturing — without per-domain configuration
in the default open-vocabulary mode. Customer corrections persist
into a per-tenant pattern memory and replay automatically on the next
similar document, which is what makes the system "self-train."

---

## 2. The 6-tier architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  Tier 1 — Brain                                                     │
│    7 cognitive organs + 7 supporting layers                         │
│    Eyes · Pattern Cortex · Hands · Conscience · Hippocampus ·       │
│    Inner Voice · Insight Cortex                                     │
│    Coverage · Account Briefing · Narrator · Chat ·                  │
│    Knowledge Graph · Graph Builder · Entity Resolver                │
├──────────────────────────────────────────────────────────────────────┤
│  Tier 2 — Knowledge Graph (Postgres-backed, NetworkX-shaped API)    │
│    12 node types · 11 edge types · per-tenant via RLS               │
├──────────────────────────────────────────────────────────────────────┤
│  Tier 3 — Domain Packs (OPTIONAL — open-vocabulary is default)      │
│    Each pack = YAML manifest of 13 mandatory skill slots            │
│    business_documents_base ships; telecom / healthcare / cloud /    │
│    legal / manufacturing live in Appendix A.2–A.6 as spec           │
├──────────────────────────────────────────────────────────────────────┤
│  Tier 4 — Tenant Configs                                            │
│    tenants.config JSONB · per-tenant cost caps, eval thresholds,    │
│    pack assignment, custom routing overrides                         │
├──────────────────────────────────────────────────────────────────────┤
│  Tier 5 — Kernel                                                    │
│    Ingest · LLM Gateway · Pack Loader · Auth (JWT+API+RLS) ·        │
│    Job Queue (Celery+Redis) · Observability (structlog+Langfuse) ·  │
│    Settings · Provider Router                                        │
├──────────────────────────────────────────────────────────────────────┤
│  Tier 6 — Data and Memory                                           │
│    Postgres 15 · JSONB · pgvector (HNSW cosine) · sentence-         │
│    transformers BGE-M3 embeddings · entity_merge_proposals queue    │
└──────────────────────────────────────────────────────────────────────┘
```

**Why the layering matters for reusability**:
- Tier 5 (Kernel) knows nothing about industries — it's the chassis.
- Tier 3 (Packs) knows nothing about Kernel internals — it's the contract.
- Tier 1 (Brain) reads from Tier 6 and writes through Tier 5.
- New domains land in Tier 3 or Tier 4. Never in Tier 5.

---

## 3. The 19-stage pipeline

```
                  ┌─────────────────────────────────────────┐
                  │  Phase 1 — per-document                 │
                  │                                         │
   upload → [0] page-limit gate (UI)                        │
                  │                                         │
            [1] ingest (Kernel)            ──────────┐      │
            [2] classify (Eyes)            Flash     │      │
            [3] memory check (Hippo)       no LLM    │      │
                  │           ├── HIT? skip Pattern Cortex ─┤
            [4] schema discovery           Pro              │
                (Pattern Cortex)                            │
            [5] rule invention             Pro       gated │
                (Conscience.invent)                  on    │
            [6] correction lookup (Hippo)  no LLM           │
            [7] extract (Hands)            Flash+Vision    │
            [8] validate (Conscience)      simpleeval      │
            [9] memory write (Hippo)       + RAG index    │
                  └─────────────────────────────────────────┘

                  ┌─────────────────────────────────────────┐
                  │  Phase 2 — batch analysis               │
                  │                                         │
           [10] insights (Insight Cortex)   heuristic + Pro │
           [11] reflection (Inner Voice)    pure Python     │
           [12] group discovery             pure Python     │
           [13] coverage classification     pure Python     │
                  └─────────────────────────────────────────┘

                  ┌─────────────────────────────────────────┐
                  │  Phase 3 — report assembly              │
                  │                                         │
           [14] account briefings           pure Python     │
           [15] narrator                    Pro             │
           [16] BatchReport assembly        Pydantic        │
                  └─────────────────────────────────────────┘

                  ┌─────────────────────────────────────────┐
                  │  Phase 4 — knowledge graph              │
                  │                                         │
           [17] graph build                 UPSERT + KG     │
                + entity resolution         rapidfuzz       │
           [18] graph insights              degree/isolated │
           [19] cross-doc validation        Pydantic        │
                  └─────────────────────────────────────────┘

                              ▼
                       BatchReport
                       (JSON, served via API or rendered in UI)
```

**Stage I/O contracts (one row per stage; every contract is a Pydantic v2 model):**

| # | Stage | Input | Output | LLM? |
|---|---|---|---|---|
| 0 | page-limit gate | `bytes`, `mime_type` | reject or proceed | – |
| 1 | ingest | `bytes`, `filename` | `IngestedDocument` | – |
| 2 | classify (Eyes) | `IngestedDocument` | `Cluster` | Flash |
| 3 | memory check | `Cluster` | `MemoryHit` or `None` | – |
| 4 | schema discovery | `IngestedDocument`, `Cluster` | `Schema` | Pro |
| 5 | rule invention | `Schema`, `Cluster` | `RuleSet(invented=true, enabled=false)` | Pro (gated) |
| 6 | correction lookup | `Cluster` | `list[CorrectionHint]` | – |
| 7 | extract (Hands) | `IngestedDocument`, `Cluster`, `Schema`, `corrections` | `Extraction` | Flash + Vision |
| 8 | validate (Conscience) | `Extraction`, `RuleSet` | `ValidationResult` | – |
| 9 | memory write | `Cluster`, `Schema`, `RuleSet`, `Extraction` | `pattern_id`, RAG chunks | – |
| 10 | insights | `list[Extraction]`, `list[Anomaly]` | `list[Insight]` | optional Pro |
| 11 | reflection | `list[Extraction]`, `list[Anomaly]` | `Reflection` | – |
| 12 | group discovery | `dict[str, Extraction]` | `list[DocumentGroup]` | – |
| 13 | coverage classification | `list[DocumentGroup]`, `clusters` | annotated `list[DocumentGroup]` | – |
| 14 | account briefings | `groups`, `extractions`, `clusters` | `list[AccountBriefing]` | – |
| 15 | narrator | KPIs + top insights | `str` (1 paragraph) | Pro |
| 16 | BatchReport assembly | all of the above | `BatchReport` | – |
| 17 | graph build | `BatchReport`, EntityResolver | `GraphDelta`, KG nodes + edges | – |
| 18 | graph insights | KG | degree centrality, isolated nodes | – |
| 19 | cross-doc validation | KG, `Extraction` references | flag missing-reference anomalies | – |

The **only place the LLM enters** is stages 2, 4, 5, 7, 10 (optional), 15. Every other stage is deterministic Python — which means the pipeline degrades gracefully when the LLM is unreachable: heuristics fire, no synthesis is produced, but the documents still ingest, extract via the previous pattern, validate, and persist.

---

## 4. The 7 cognitive organs

Each organ is a Python module under `src/mdi/brain/`. Each has a clear
input/output contract, can be tested in isolation against `FakeGateway`,
and can be swapped without changing other organs.

| Organ | File | Job | Cost tier |
|---|---|---|---|
| **Eyes** | `eyes.py` | Open-vocabulary classification — industry, vendor, doc_type, layout, language | perception (Flash) |
| **Pattern Cortex** | `pattern_cortex.py` | Schema discovery — propose a field schema from the doc | reasoning (Pro) |
| **Hands** | `hands.py` | Field extraction with vision routing + correction injection | extraction (Flash + Vision) |
| **Conscience** | `conscience.py` | Two modes: **invent** new validation rules from a schema (gated); **validate** rules against an extraction via `simpleeval` | reasoning (Pro) for invent |
| **Hippocampus** | `hippocampus.py` | Pattern memory + correction memory + RAG embedder | – (pgvector) |
| **Inner Voice** | `inner_voice.py` | Per-pattern verdict: strong / watch / weak | – |
| **Insight Cortex** | `insight_cortex.py` | 6 analysis types: trend · cross-doc · peer · pattern detection · risk · optimization | optional Pro |

## 5. The 7 supporting layers

Same `src/mdi/brain/` directory, complementary roles:

| Layer | Job |
|---|---|
| Coverage classifier | Classify document groups as full / partial / orphan |
| Account Briefing | Per-account reconciliation (money / timeline / actions / risks) |
| Narrator | One-paragraph executive summary |
| Chat | Graph-routed for relationship Qs; LLM+RAG for synthesis Qs |
| Knowledge Graph | Postgres-backed with NetworkX-shaped read API |
| Graph Builder | Convert `BatchReport` → KG nodes/edges with entity resolution |
| Entity Resolver | rapidfuzz fuzzy matching with auto / review / reject tiers |

---

## 6. The self-training loop (the moat)

This is what customers pay for and where MDI compounds value over time.
It is **not classical ML training** — there is no gradient descent, no
model fine-tuning, no per-customer weight updates. It is a
**corrections-replay loop** powered by per-tenant pattern memory.

```
Run 1 ───────────────────────────────────────────────────────────────
  1. Analyst uploads invoice
  2. Hands extracts:     account_number = "133442501"
  3. Analyst opens Train page, says: "actual value is '0133442501'"
       (preserve leading zero)
  4. Correction stored in Hippocampus with:
        scope     = (industry, vendor, doc_type) = ("telecom","AT&T","invoice")
        signature = (scope, field_path, value)
        agreement_count = 1

Run 2 ──── new invoice, same scope ─────────────────────────────────
  5. Eyes classifies → same scope
  6. Orchestrator calls Hippocampus.get_corrections(scope)
  7. Hands prompt receives the correction inline:
        "PAST CORRECTIONS — apply these unless the document clearly
         contradicts:
           - account_number should be '0133442501' (was extracted as
             '133442501'; user-corrected 1x).
             Note: preserve leading zeros"
  8. Gemini extracts the corrected value automatically.

Run N+ ──── pattern stabilises ────────────────────────────────────
  9. Same correction submitted again → agreement_count++
 10. After threshold (typically 3+), the brain treats it as a strong
     rule; Inner Voice's verdict for that pattern becomes "strong".
```

Three properties that make this a moat:

1. **Per-tenant via RLS** — `corrections.tenant_id` is hard-isolated at the database layer. Customer A's corrections never leak into Customer B's prompts.
2. **Scope-aware** — a correction for AT&T's account-number format doesn't apply to Verizon. The (industry, vendor, doc_type) tuple keeps domains separate.
3. **Compounding** — every correction makes future extractions of similar docs cheaper (memory hit ⇒ Pattern Cortex skipped) AND more accurate (corrections replay into the prompt).

Synthesised accuracy curve from the POC: **Day 1 ≈ 75%, Month 3 ≈ 95%+** on a customer's specific document types. (Validated structurally in live tests; held-out accuracy on a golden set is still a gap — `GAP_ANALYSIS.md` Gap 4.)

---

## 7. What makes the platform generic

Three abstractions, designed to compose:

### 7.1 The Kernel / Pack / Tenant separation

```
┌─────────────────────────────────────────────────────────────────┐
│  KERNEL — industry-agnostic                                     │
│  Code lives in src/mdi/kernel/. Knows nothing about industries. │
│  Same code runs telecom, healthcare, cloud, legal, manufacturing.│
└─────────────────────────────────────────────────────────────────┘
                          ▲
                          │ (kernel calls into packs by slug)
                          │
┌─────────────────────────────────────────────────────────────────┐
│  PACK — vertical-specific (OPTIONAL)                            │
│  YAML+Markdown bundle under src/mdi/packs/<slug>/.              │
│  13 mandatory skill slots (synthesis Appendix A.7).             │
│  Adding a new vertical = author 1 pack ≈ 1-2 weeks.             │
└─────────────────────────────────────────────────────────────────┘
                          ▲
                          │ (tenant assigns or stays open-vocab)
                          │
┌─────────────────────────────────────────────────────────────────┐
│  TENANT CONFIG — issuer-specific (PER-CUSTOMER)                 │
│  tenants.config JSONB. eval_thresholds, cost caps, routing      │
│  overrides, pack_slug, custom field aliases.                    │
│  New customer = INSERT into tenants ≈ 30 seconds.               │
└─────────────────────────────────────────────────────────────────┘
```

The kernel never imports from packs or tenants. Packs never import from
the kernel — they're loaded by string slug at runtime via
`pack_loader.load_pack(slug)`. Tenants are read at runtime from Postgres.
This means **the kernel is shippable as a frozen artifact** while packs
and tenant configs change daily.

### 7.2 Pydantic v2 contracts at every layer boundary

Every organ's input and output is a typed Pydantic model with
`extra="forbid"`. Adding a new field is a one-line schema change. The
type system guarantees that an organ's output is consumable by the next
organ without runtime adapters or untyped dicts. This is what lets us
**swap an organ** (e.g., replace `Hands` with a different LLM provider's
client) without changing anything downstream.

### 7.3 Provider routing as a separate concern from the brain

The brain organs don't know about Gemini or Claude. They call
`gateway.generate(tier="perception"|"extraction"|"reasoning"|"synthesis")`.
The provider router (`kernel/provider_router.py`) maps tiers to
concrete provider+model pairs **per call**, with a fallback chain
(Gemini → Claude). This means **the same brain runs on different LLM
providers** without code changes — only `.env` configuration.

---

## 8. Three reusable shapes (pick the one that fits your project)

### Shape A — Embed as a library

For Python projects that want the brain in-process.

```python
import asyncio
import uuid
from mdi.orchestrator.pipeline import run_batch_async

async def process(files):
    payloads = [{"filename": f.name, "content": f.read_bytes()} for f in files]
    return await run_batch_async(
        tenant_id=str(uuid.uuid4()),   # one tenant per consuming app
        payloads=payloads,
        persist=False,                  # skip the DB layer entirely
    )

report = asyncio.run(process(my_files))
print(report["narrator_summary"])
```

Or call a single organ in isolation:

```python
from mdi.brain import eyes, hands
from mdi.kernel.ingest import ingest

doc = ingest("invoice.pdf", path.read_bytes())
cluster = await eyes.classify(doc)
extraction = await hands.extract(doc, cluster, schema, corrections=[])
```

### Shape B — Hit the REST API

For non-Python projects (Node, Go, mobile, etc.).

```bash
docker compose up -d
alembic upgrade head
mdi-api    # http://localhost:8080
```

| Verb | Path | Purpose |
|---|---|---|
| `POST` | `/process` | multipart files → BatchReport JSON |
| `GET` | `/report/{batch_id}` | fetch a previously-run batch |
| `POST` | `/chat` | conversational Q&A (graph + RAG hybrid) |
| `POST` | `/correction` | submit an analyst correction |
| `GET` | `/tenant/usage` | spend + cap status |
| `GET` | `/merges` | list entity-merge proposals |
| `POST` | `/merges/{id}/approve` · `/reject` | act on a merge proposal |
| `GET` | `/admin/tenants` (admin auth) | list tenants |
| `POST` | `/admin/tenants` (admin auth) | create + issue first API key |
| `GET` | `/admin/packs` (admin auth) | list available packs |
| `GET` | `/admin/packs/{slug}` (admin auth) | inspect full pack contract |
| `PATCH` | `/admin/tenants/{id}` (admin auth) | update pack / cap / display name |
| `POST` | `/admin/tenants/{id}/api_keys` (admin auth) | rotate / issue additional key |

Auth: per-tenant `X-API-Key`, admin via `X-Admin-Key`. Both checked via
`hmac.compare_digest` against settings.

### Shape C — Contribute a pack

For domain experts who want to add a new vertical without writing Python.

```
packs/<your-vertical>/
├── skills.yaml              # the manifest — 13 mandatory slots
├── schema/
│   ├── fields.yaml          # field schema for the vertical
│   └── doc_types.yaml       # doc-type taxonomy
├── prompts/
│   ├── <doc_type_a>.md      # Hands prompt guidance per doc type
│   └── …
├── rules/
│   ├── validators.yaml      # Conscience validation rules
│   ├── merge.yaml           # multi-doc merge authority per field
│   └── compliance.yaml      # data-retention, PII, audit
├── enrichment/
│   ├── codes.yaml           # currency codes, country codes, etc.
│   └── aliases.yaml         # known abbreviations
└── classifier/
    └── signals.yaml         # keyword cues per doc type
```

Then in any tenant's config: `pack_slug = "<your-vertical>"`. The brain
picks it up on the next batch — no code change, no restart, no
redeploy. Inspect the existing `business_documents_base` for a working
example, or use the Admin tab's "Inspect a pack" panel.

---

## 9. Extension recipes

### 9.1 Add a new vertical (1-2 weeks)

1. **Copy** `packs/business_documents_base/` to `packs/<your-vertical>/`.
2. **Author** `skills.yaml` per the 13 mandatory slots.
3. **Replace** field schema, prompts, validators with vertical-specific content.
4. **Drop** 10+ sample documents into `eval/golden/<your-vertical>/`.
5. **Add** a `golden.yaml` with expected extractions.
6. **Run** `pytest -m live_llm` to validate against your golden set.
7. **Tag** version 1.0.0 when held-out accuracy ≥ 90%.

### 9.2 Add a new LLM provider

1. **Subclass** `BaseProvider` in `src/mdi/kernel/providers/<name>_provider.py`.
2. **Implement** `call(...)` returning `ProviderCallResult`.
3. **Register** via `register_provider("<name>", <name>Provider)` at import.
4. **Add** to `provider_router._POLICY` for whichever tiers it serves.
5. **Add** `<NAME>_API_KEY` to `.env.example` + `settings.py`.

No brain organ changes. The new provider is available immediately to
every organ that uses tier-based routing.

### 9.3 Add a new organ

1. **Create** `src/mdi/brain/<organ>.py` with a clear input/output Pydantic
   contract.
2. **Add** stage I/O contracts to `src/mdi/models/schemas.py`.
3. **Wire** into `src/mdi/orchestrator/pipeline.py` at the right stage.
4. **Add** an `EvalLayer` in `src/mdi/eval/stage_eval.py` for the new
   stage; register it via `STAGE_EVALS["<key>"] = <YourEval>`.
5. **Unit test** with `FakeGateway` in `tests/unit/test_<organ>.py`.

The orchestrator picks it up via the wiring; nothing else changes.

### 9.4 Add per-tenant customization

1. **Add** the new field to `tenants.config` JSONB. No migration needed.
2. **Read** it where you need it: `tenant.config.get("<field>", <default>)`.
3. **Surface** it in the Admin tab's tenant-edit panel.

Per-tenant `eval_thresholds` works this way today.

---

## 10. The data contracts (the glue)

Every interaction across the system flows through one of these Pydantic
shapes. Adding a new field to one of these is the **only** place a
schema change is needed for it to flow through every layer.

```python
# Tier 1: per-stage outputs
IngestedDocument     # what ingest returns
Cluster              # what Eyes returns
Schema               # what Pattern Cortex returns
RuleSet, Rule        # what Conscience.invent returns
Extraction, FieldExtraction  # what Hands returns
ValidationResult, Anomaly    # what Conscience.validate returns
MemoryHit, CorrectionHint    # what Hippocampus returns
Reflection           # what Inner Voice returns
Insight              # what Insight Cortex returns

# Tier 2: knowledge graph
NodeType, EdgeType, GraphDelta

# Tier 3: aggregate
DocumentGroup, MoneyPicture, TimelineEvent,
ActionItem, AccountBriefing, BatchReport

# Tier 4: conversation
ChatRequest, ChatResponse, ChatTurn

# Tier 5: cost
LLMCall
```

All of them live in `src/mdi/models/schemas.py`. They use
`extra="forbid"` so an organ can't silently emit unknown fields. Strict
boundaries make the brain composable.

---

## 11. Operational checklist (running it as a standalone product)

When someone wants to take MDI and run it as their own product, the
checklist:

| Concern | Where it lives today | What to do at deploy time |
|---|---|---|
| **Secrets** | `.env`, gitignored | Move to your secret manager (AWS Secrets Manager, Vault, GCP Secret Manager) |
| **Postgres** | `docker-compose.yml` local | Hosted Postgres with pgvector ≥ 0.5 (RDS, Supabase, Neon, Aiven) |
| **Redis** | `docker-compose.yml` local | Hosted Redis (Elasticache, Upstash, Render) |
| **App role** | `mdi_app` (NOSUPERUSER, NOBYPASSRLS) | Same — RLS depends on the role not being a superuser |
| **API server** | `uvicorn` on 8080 | gunicorn + uvicorn workers behind a load balancer |
| **Streamlit UI** | port 8501, internal team only | Keep behind VPN or auth proxy; never expose direct |
| **Backups** | none | nightly `pg_dump` + WAL archiving |
| **Eval gate** | `pytest -m live_llm` | Run as a nightly job; alert on accuracy drift |
| **Cost cap** | per-tenant `monthly_cost_cap_usd` | Make sure `BudgetExceeded` is surfaced in your observability stack |
| **Observability** | structlog (default), Langfuse (opt-in) | Wire Langfuse keys for LLM-call tracing |
| **Provider failover** | Gemini → Claude (built in) | Verify both keys are stocked and rotated quarterly |
| **Migrations** | `alembic upgrade head` | Run as part of CI/CD with the migration role (superuser) |
| **CI checks** | offline pytest + mypy + ruff | Add the security test (cross-tenant access attempts) on every PR |

---

## 12. Glossary

- **Brain**: the 7 cognitive organs + 7 supporting layers. The product.
- **Kernel**: industry-agnostic plumbing. The chassis.
- **Open-vocabulary mode**: Eyes detects industry/vendor/doc_type from content alone. Default mode.
- **Pack**: optional declarative bundle for a vertical. YAML + Markdown. 13 mandatory skill slots.
- **Tenant Config**: per-issuer overrides layered on top of a pack base or open-vocabulary defaults.
- **Pattern Memory**: vector-indexed store of patterns scoped per (vendor, industry, doc_type). The moat.
- **Knowledge Graph**: persistent Postgres-backed graph of business entities and their relationships.
- **Insight Cortex**: the seventh brain organ; comparative analysis.
- **Account Briefing**: per-account reconciliation report (money / timeline / actions / risks).
- **BatchReport**: the unified output object the orchestrator produces.
- **Memory hit**: cosine-similarity match in Hippocampus that short-circuits Pattern Cortex (the cost-saving moment).
- **Corrections-replay loop**: analyst correction → Hippocampus → replays into Hands' next prompt for the same scope → agreement count compounds. The self-training mechanism.
- **EvalLayer**: per-stage post-check that scores an organ's output deterministically; surfaces silent degradation.
- **RAG sidecar**: doc_chunks table + retriever that feeds the Chat synthesis layer with grounded context (separate from pattern memory).
