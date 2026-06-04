# MDI — Modular Data Intelligence

A reusable, multi-domain document intelligence brain. Reads invoices, purchase orders, contracts, claims, statements across any industry; learns from corrections; surfaces analyst-grade insights. Multi-tenant from day one.

## Quick start

```bash
# 1. Bring up Postgres (with pgvector) + Redis
docker compose up -d

# 2. Install package
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 3. Configure
cp .env.example .env
# edit .env — at minimum set GOOGLE_API_KEY (or skip and run tests offline)

# 4. Migrate
alembic upgrade head

# 5. Start API + analyst UI
mdi-api    # http://localhost:8080
mdi-ui     # http://localhost:8501

# 6. Run the smoke test (no Gemini needed — uses FakeGateway)
pytest tests/integration/test_smoke.py -v
```

## Architecture (six tiers)

```
┌────────────────────────────────────────────────┐
│  Tier 1 — Brain                                │
│   7 organs:  Eyes, Pattern Cortex, Hands,      │
│              Conscience, Hippocampus,          │
│              Inner Voice, Insight Cortex       │
│   7 layers:  Coverage, Account Briefing,       │
│              Narrator, Chat, Knowledge Graph,  │
│              Graph Builder, Entity Resolver    │
├────────────────────────────────────────────────┤
│  Tier 2 — Knowledge Graph (Postgres-backed)    │
├────────────────────────────────────────────────┤
│  Tier 3 — Domain Packs (optional)              │
├────────────────────────────────────────────────┤
│  Tier 4 — Tenant Configs                       │
├────────────────────────────────────────────────┤
│  Tier 5 — Kernel                               │
│   ingest · llm_gateway · pack_loader ·         │
│   job_queue · auth · observability             │
├────────────────────────────────────────────────┤
│  Tier 6 — Data and Memory                      │
│   Postgres 15 + JSONB + pgvector (HNSW)        │
└────────────────────────────────────────────────┘
```

## The 19-stage pipeline

| Phase | Stages | Owner |
|---|---|---|
| 1 — per-doc | 0 page-gate · 1 ingest · 2 classify (Eyes) · 3 memory check (Hippocampus) · 4 schema discovery (Pattern Cortex) · 5 rule invention (Conscience) · 6 correction lookup (Hippocampus) · 7 extract (Hands) · 8 validate (Conscience) · 9 memory write (Hippocampus) | Kernel + Brain |
| 2 — batch | 10 comparative analysis (Insight Cortex) · 11 reflection (Inner Voice) · 12 group discovery · 13 coverage classification | Brain |
| 3 — report | 14 account briefings · 15 narrator · 16 BatchReport assembly | Brain |
| 4 — graph | 17 graph build · 18 graph insights · 19 cross-doc validation | Brain |

## Multi-tenant isolation

Postgres **row-level security** filters every tenant-scoped table by `current_setting('app.tenant_id')`. The `auth.tenant_session()` dependency in [src/mdi/kernel/auth.py](src/mdi/kernel/auth.py) sets that GUC on every request before any query runs. App-level checks are a defense-in-depth layer, not the primary boundary.

## Cost controls

- Daily global cap from `.env` (default $5)
- Per-tenant monthly ceiling from `tenants.monthly_cost_cap_usd`
- Soft warning at 80%, hard cap at 100% with override flag
- Page-limit gate (`PAGE_LIMIT_SOFT` triggers UI confirmation; `PAGE_LIMIT_HARD` rejects)
- Every LLM call routes through the [LLM Gateway](src/mdi/kernel/llm_gateway.py); no direct Gemini calls anywhere else

## Self-improvement loop

Every analyst correction is stored in Hippocampus with scope `(industry, vendor, doc_type)` and replays automatically into Hands' prompt for the same scope on the next batch. After three or more agreements the brain treats the correction as a strong rule. The accuracy curve from the POC: ~75% Day 1 → ~95% Month 3, customer-specific.

## Testing

- All tests run **offline** by default — every LLM call is replayed by [`FakeGateway`](tests/fake_gateway.py).
- Real Gemini calls only happen via the explicit, opt-in eval harness (`pytest -m live_llm`).
- Integration tests need Postgres + Redis (`docker compose up -d`).
- Security test attempts cross-tenant access on every RLS-protected table and asserts denial.

## Repo layout

```
mdi/
  src/mdi/
    kernel/         # ingest, llm_gateway, auth, pack_loader, job_queue, observability
    brain/          # 7 organs + 7 supporting layers
    orchestrator/   # 19-stage pipeline + progress events
    models/         # Pydantic v2 schemas + SQLAlchemy db models
    api/            # FastAPI app
    ui/             # Streamlit analyst UI
    eval/           # golden datasets + harness
    packs/          # optional vertical packs (business_documents_base ships by default)
  tests/            # unit · integration · eval · fixtures · fake_gateway
  migrations/       # alembic
```

## Phase status

| Phase | Status | Exit criterion |
|---|---|---|
| 1 — Foundation | **scaffolded** | Smoke test green; two test tenants run in parallel without seeing each other's data |
| 2 — Brain organs | stubs in place | All 7 organs unit-tested with FakeGateway; ≥80% line coverage |
| 3 — KG + supporting layers | stubs in place | KG survives concurrent writes from two tenants |
| 4 — Pipeline + API + UI | stubs in place | 15 sample PDFs across 5 industries → BatchReport in <2 min |
| 5 — Eval + hardening | stubs in place | Held-out accuracy ≥ 90% on extractable fields |

## License

Proprietary. Internal use only.
