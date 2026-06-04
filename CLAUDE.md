# Project context for future Claude Code sessions

This file is auto-loaded into every Claude Code session opened in this repo. It captures the architectural decisions that have already been made so they don't need to be relitigated.

## Source of truth

The synthesis document at `/Users/harivershan/Downloads/Modular_Data_Intelligence_Synthesis.docx` is authoritative. If anything in code conflicts with it, the doc wins. Sections 11–21 specify the architecture; Section 21 has the 8-week phased plan; Section 23 lists the eight open decisions and their recommended resolutions.

## Locked decisions (do not relitigate)

1. **Open-vocabulary by default.** Pack contract is optional — only added for clients with contractual schema guarantees. Open-vocabulary is the POC pattern that proved out across five industries.
2. **Build on the POC pattern, not greenfield.** The kernel-on-top-of-running-code shape is what we hardened.
3. **Multi-tenant isolation = Postgres RLS.** App-level checks are a defense-in-depth layer; RLS is the primary boundary.
4. **Conscience-invented rules are gated.** First invocation per `(vendor, doc_type)` requires analyst review. Type-derived baseline rules are always-on. Env flag: `ENABLE_INVENTED_RULES=false` in production.
5. **Job queue = Celery + Redis.** Battle-tested; Temporal was considered and rejected for v1.
6. **Pack registry = internal-only for v1.** Partner-built packs deferred to v1.1.
7. **Per-tenant cost ceiling: soft warn at 80%, hard cap at 100%, manual override path.**
8. **Streamlit for analyst UI; React + Tailwind for customer-facing onboarding (v1.1+).** Don't migrate the analyst UI off Streamlit.
9. **LLM routing = Gemini-primary with Claude fallback chain** (Hari, 2026-05-07). Per-tier:
   - perception: Gemini Flash → Claude Haiku
   - extraction: Gemini Flash → Claude Sonnet
   - reasoning:  Gemini Pro   → Claude Opus
   - synthesis:  Gemini Pro   → Claude Opus
   See `kernel/provider_router.py::_POLICY`. Fallback fires only on
   retryable failures (rate limits, 5xx, timeouts, missing key). Non-
   retryable errors surface immediately — no point retrying a 401 on
   the next provider.
10. **DB roles: `mdi` (superuser, migrations only) and `mdi_app` (runtime)**.
    Superusers bypass RLS unconditionally — even with `FORCE ROW LEVEL
    SECURITY` set. The runtime DATABASE_URL must point at `mdi_app`
    (NOSUPERUSER, NOBYPASSRLS) or RLS is silently disabled. Alembic and
    `psql` admin work continue to use `mdi`. Bootstrap SQL:
    ```sql
    CREATE ROLE mdi_app LOGIN PASSWORD '...' NOSUPERUSER NOBYPASSRLS;
    GRANT USAGE ON SCHEMA public TO mdi_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO mdi_app;
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO mdi_app;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO mdi_app;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO mdi_app;
    ```
11. **`tenant_session()` uses `set_config(..., is_local=False)`**.
    Transaction-local GUCs evaporate at the first `db.commit()` (which
    the orchestrator does mid-pipeline). Session-local survives. We
    reset on session exit so pooled connections don't carry tenant
    context across requests.

## Tech stack (locked)

| Layer | Tool |
|---|---|
| LLM perception/extraction | Gemini 2.5 Flash + Vision |
| LLM reasoning/discovery | Gemini 2.5 Pro (2M context) |
| LLM Gateway | custom — tenacity retry, CostTracker, 120s timeout, multimodal |
| Orchestration | asyncio + `Semaphore(5)` per organ; LangChain only inside Chat layer |
| Observability | Langfuse (no-op when keys absent) |
| Structured memory | Postgres 15+ with JSONB |
| Vector memory | pgvector + HNSW (cosine ops) |
| Embeddings | sentence-transformers BAAI/bge-m3, in-process |
| Knowledge graph | Postgres-backed adjacency list (kg_nodes/kg_edges); NetworkX-compatible API |
| API | FastAPI + Pydantic v2 |
| Job queue | Celery + Redis |
| Doc parsing | pypdf, python-docx, openpyxl, pandas, Pillow |
| Pack format | YAML + Markdown |
| UI | Streamlit (analyst), React (customer-facing — v1.1+) |
| Safety | simpleeval (sandboxed) + tenacity + custom CostTracker |
| Auth | JWT + per-tenant API keys + Postgres RLS |
| Tests | pytest + pytest-asyncio + custom FakeGateway |

## Quality gates (CI must enforce)

- `pytest` full suite green offline (FakeGateway).
- `mypy --strict src/mdi` green.
- `ruff check src/mdi` green.
- Alembic migration check (heads count == 1).
- Cross-tenant security test green on every push.
- Every brain organ unit-tested with FakeGateway; no organ requires real Gemini for its tests.
- Every LLM call routes through the LLM Gateway. Direct `google.generativeai` imports outside `kernel/llm_gateway.py` should fail review.
- Every cost-incurring call is tracked by CostTracker before it fires; over-cap calls raise `BudgetExceeded`.
- Every DB write happens inside a tenant context (`current_setting('app.tenant_id')` set).
- Pydantic v2 contracts at every layer boundary — no untyped dict-passing between organs.

## Daily workflow

After every meaningful change:

1. `pytest`
2. `mypy --strict src/mdi`
3. `ruff check src/mdi`
4. Add or update tests in the same commit.
5. Update this file if any architectural decision changed.

Commit messages: imperative, scoped (`kernel: add tenant cost cap to LLM Gateway`).
Branch naming: `phase-N-feature-name` (`phase-2-pattern-cortex`).

## Decide yourself vs. ask

**Decide yourself:** implementation details, helper functions, file organization within a module, library choices when synthesis doc doesn't specify, test layout, log levels, SQL optimizations.

**Ask before:**
- Deviating from the architecture in the synthesis doc.
- Deviating from the locked tech stack.
- Schema changes beyond what's in the migration.
- Adding any external service beyond Gemini, Postgres, Redis, Langfuse.
- Skipping a phase exit criterion.
- Replacing a brain organ with a third-party library.
- Changing the multi-tenant isolation approach.
