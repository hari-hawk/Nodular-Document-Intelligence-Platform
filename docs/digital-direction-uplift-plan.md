# MDI ← Digital Direction Uplift Plan

**Author**: 2026-06-04, based on analysis of `hari-hawk/Digital-Direction-New-Platform`
**Goal**: Pull the *generic* patterns from Digital Direction into MDI's common base so MDI becomes the reusable platform; Digital Direction (and any future vertical) sits on top as a pack — not a fork.

---

## TL;DR positioning

> MDI is the **document intelligence platform**. Digital Direction becomes the **telecom vertical** that runs on it.
> Future verticals (insurance, cloud finance, healthcare, manufacturing, legal-HR) plug in via the same pack contract.

What MDI gets from this uplift:
1. **Self-evolving vendor recognition** — unknown vendors auto-register a pack stub at runtime.
2. **Deterministic insight layer** — pure-function detectors that complement the LLM Insight Cortex (faster, cheaper, more reliable for the obvious patterns).
3. **Corrections-as-memory** — analyst corrections embed into pgvector, retrievable on the next similar document.
4. **Pre-classification content signals** — regex/phrase match on page 1 before paying for an LLM classify call.
5. **Self-hosted observability** — Langfuse traces every LLM call with cost + prompt + response.
6. **Vertex AI provider** — fixes the `google.generativeai` deprecation warning we hit and gives a more reliable Gemini path.
7. **Per-tenant master-data store** — contract terms, known accounts, expected addresses persist across uploads.
8. **Next.js frontend** — replaces Streamlit for the demo-able product surface.

What we deliberately do NOT pull in: the 60-field telecom schema, USOC codes, carrier-specific YAML logic, phone-number splitting. Those stay in the (future) `mdi/packs/telecom/` pack — MDI's common base stays domain-neutral.

---

## What Digital Direction has that's worth porting

| DD module | Lines | What it does | Why it's generic | Map to MDI |
|---|---:|---|---|---|
| `backend/services/auto_carrier_registry.py` | ~150 | When LLM emits unknown vendor, write minimal `carrier.yaml` so future uploads recognize it without a PR / restart. Blocklist + sanity filter prevents hallucinated names from registering. | "Auto-register unknown entity from LLM output" — totally generic. | New `mdi/kernel/auto_pack_registry.py` |
| `backend/services/patterns.py` | ~600 | 5 deterministic detectors over extracted rows: recurring vendors, pricing anomalies (>Nσ), contract expirations, multi-carrier same account, M2M needing contracts. Pure functions, plain-dict Findings. | 3 of 5 (`recurring_vendors`, `pricing_anomalies`, `contract_expirations`) are domain-neutral. Other 2 fit a "manufacturing" or "cloud" vertical with slightly different signatures. | New `mdi/brain/detectors/` package. Insight Cortex (LLM) remains, but cheap signals fire first. |
| `backend/services/learning.py` | ~200 | Embeds analyst corrections (carrier+doc_type+field+before/after+snippet) into pgvector via the existing `corrections` table. Two-tier recall: exact match → vector ANN. | The "embed correction context → retrieve when similar doc shows up" loop is generic. MDI has corrections but doesn't embed them. | Extend `mdi/brain/hippocampus.py` with a `lookup_correction()` path. |
| `backend/services/domain_packs.py` | ~250 | `DomainPack` dataclass with `content_signals` (regex/phrase) for detecting which pack a document belongs to from page-1 text, before invoking the LLM classifier. | MDI's Eyes does this with an LLM. Adding content_signals = faster + cheaper for known formats. | New `content_signals:` block in `packs/<pack>/pack.yaml`. Eyes consults it first. |
| `backend/services/spend_ledger.py` | ~120 | File-backed atomic counter, raises `SpendCapExceeded` before any LLM call goes over the configured cap. Persists across restarts. | MDI has `CostTracker` (in-memory per-batch). DD's cumulative ledger across runs/processes is stronger. | Replace or extend `mdi/kernel/cost_tracker.py`. |
| `backend/pipeline/compliance.py` | ~300 | Deterministic post-merge compliance flags: rate mismatch (invoice vs contract), expired contract, MTM inconsistency, term-date mismatch, no-contract billing. | Generic shape; the rules themselves are domain-specific but the framework is reusable. | New `mdi/brain/compliance.py` taking a `ComplianceCheck` plugin per pack. |
| LangFuse self-hosted docker integration | (docker-compose entry) | Self-hosted trace UI for every LLM call. Filter by model / name / metadata. | Drop-in; no platform-coupling. | Add `langfuse:` service to MDI `docker-compose.yml` + thin LangFuse client wrapper in `mdi/kernel/llm_gateway.py`. |
| Vertex AI backend (`backend/services/llm.py` + `LLM_BACKEND=vertex` env) | (~200) | Routes Gemini calls through Vertex AI instead of AI Studio for better 503 reliability + IAM-based auth. | The current `mdi/kernel/providers/gemini_provider.py` uses the deprecated `google.generativeai` package — Vertex via `google.genai` is the new path. | New `mdi/kernel/providers/vertex_provider.py`, register in the provider router. |
| `backend/services/master_data.py` | ~250 | Per-client persistent knowledge store — contract terms, expected addresses, known circuits — carries forward to next month's invoice. | Generic: "per-tenant memory that survives the batch". MDI has per-batch state + Hippocampus patterns but no per-tenant key/value memory. | New `mdi/brain/master_data.py` backed by a `tenant_facts` JSONB table. |
| Frontend (Next.js + shadcn/ui, 10 page components) | ~2500 LoC | Dashboard, Upload, Results, Patterns, Review, Chat, Analytics, Clients, Settings, Bin. Login passphrase. Tailwind + dark mode. | Generic structure. 9 of 10 pages map 1:1 to capabilities MDI already exposes through Streamlit. | New `mdi/frontend/` Next.js app talking to the existing FastAPI. Streamlit stays as power-user view. |
| `scripts/graphify_semantic_build.py` | ~250 | Runs Gemini over an *allow-listed* set of source files to build a knowledge graph of code + docs + configs, surfacing cross-doc edges. | Meta-tool, helps onboard new engineers / surface dependencies. Generic. | Optional. Maybe `scripts/build_codebase_graph.py`. |

---

## What we leave behind (telecom-specific, belongs in a future `packs/telecom/`)

- 60-field telecom schema (`phone_number`, `usoc`, `mrc`, `nrc`, `circuit_id`, …)
- 67 carrier configs (AT&T, Verizon, Windstream, Spectrum, …)
- USOC code lookup tables
- Phone-number / account-number format normalisation
- Bill-of-lading / CSR / service-guide doc types
- Cross-doc merge by phone+account (the merge framework is generic; the keys are telecom)

---

## Proposed implementation in 4 waves

Each wave is independently shippable, each leaves MDI in a green-tests + green-CI state, each opens a clean PR.

### Wave 1 — Foundation lift (target: 2-3 days, ~$5 in eval reruns)

Goal: get the generic-platform wins. Zero domain changes. CI stays green.

**1.1** Add Vertex AI provider — `mdi/kernel/providers/vertex_provider.py`
- Wraps `google.genai` (new SDK), credential via service-account JSON or ADC
- Register in provider router as preferred path when `MDI_GEMINI_BACKEND=vertex`
- Falls back to `google.generativeai` for the existing AI-Studio path
- Removes the deprecation warning seen during golden eval runs

**1.2** Auto-pack registry — `mdi/kernel/auto_pack_registry.py`
- When Hands emits an unknown vendor name, append a stub entry to `packs/_auto/<slug>/pack.yaml`
- Stub uses the open-vocabulary canonical fields by default
- Blocklist filter from DD (reject `voice`, `internet`, `services`, etc. as vendor names)
- Surfaces in admin UI as "Auto-discovered vendor — review and promote"

**1.3** Content-signal pack detection — extend `packs/<pack>/pack.yaml`
- New `content_signals:` block with `required_any` phrases and `doc_type_markers` per doc type
- Eyes consults this BEFORE the LLM classifier; high-confidence regex match short-circuits the LLM call
- Backwards compatible — existing packs without `content_signals` go straight to LLM as today

**1.4** Cumulative spend ledger — `mdi/kernel/spend_ledger.py`
- File-backed atomic counter with `SpendCapExceeded` exception
- Per-backend tallies (gemini-aistudio, gemini-vertex, anthropic)
- Replaces (or wraps) the existing `CostTracker`
- Daily-cap behaviour preserved; per-tenant monthly ceiling stays in `cost_events` table

**1.5** LangFuse self-hosted — `docker-compose.yml` + `mdi/kernel/llm_gateway.py`
- Add `langfuse-web` + `langfuse-worker` + `clickhouse` services
- Trace each `LLMCall` with organ name, model, tokens, cost, request_id, prompt+response
- Off by default (env flag `MDI_LANGFUSE_HOST`); existing structlog stays as fallback

**1.6** Re-run golden eval — confirm no regression
- Same 6 packs, same 13 docs, same accuracy targets
- Cost: ~$1.70 in Gemini spend

**Exit gate**: 44/44 offline tests green, ruff clean, CI green, golden eval ≥ Run 2 numbers (4/6 packs passing).

---

### Wave 2 — Deterministic insight layer (target: 3-5 days)

Goal: complement the LLM Insight Cortex with cheap deterministic detectors. Cuts cost-per-document on common insights.

**2.1** `mdi/brain/detectors/` package
- Port the 3 generic detectors from DD's `patterns.py`:
  - `recurring_vendors.py` — vendors seen across multiple documents in a tenant's portfolio
  - `pricing_anomalies.py` — any extracted amount > Nσ from the mean for that (vendor, field) cluster
  - `expirations.py` — contracts/services with `due_date` within N days
- Each is a pure function over the BatchReport + Hippocampus state
- Findings are plain dicts (`{kind, severity, title, detail, evidence_ids, metric}`)

**2.2** Detector runner in the orchestrator
- Runs AFTER Insight Cortex in the 19-stage pipeline (or earlier, doesn't matter — pure)
- Findings merge into `BatchReport.insights` with `insight_type: "deterministic"`
- Frontend renders them next to LLM insights, marked with a different badge

**2.3** Corrections-as-memory — extend `mdi/brain/hippocampus.py`
- New `embed_correction(carrier, doc_type, field, before, after, snippet)` method
- Writes to existing `corrections` table + embedding column
- `lookup_correction(scope, field, snippet)` does exact → vector recall (DD's two-tier pattern)
- Wired into the entity-resolution approval workflow that already exists

**2.4** Per-tenant master-data store — `mdi/brain/master_data.py`
- New `tenant_facts` table — `(tenant_id, fact_type, key, value, confidence, last_seen_at)`
- Hands writes contract terms, addresses, known accounts, vendor aliases after each batch
- Eyes / Hands / Conscience can read on the next batch to bias toward known values
- Tied to RLS just like the rest of MDI

**Exit gate**: New `tests/unit/test_detectors.py` (≥ 6 cases), new `test_master_data_persistence.py`, golden eval shows ≥1 deterministic finding per relevant case.

---

### Wave 3 — UI replatform (target: 1-2 weeks)

Goal: move from Streamlit demo surface to the Next.js + shadcn/ui product surface. Streamlit stays for power users.

**3.1** Scaffold `mdi/frontend/` (Next.js 16, Tailwind, shadcn/ui, Tanstack Query)
- Auth: passphrase to start (matches DD), OAuth slot wired in but disabled
- 9 pages, each calling the existing FastAPI endpoints:
  - **Dashboard** — recent batches, cost, top insights
  - **Upload** — multi-file with progress, doc-type override, force-vision flag
  - **Results** — per-document extracted fields + source highlighting
  - **Patterns** — Hippocampus patterns + auto-discovered vendors
  - **Review** — analyst corrections + entity-merge approval queue
  - **Chat** — RAG over the tenant's documents (Chat layer already exists)
  - **Analytics** — cost over time, accuracy trends, eval results
  - **Tenants** — admin: list, create, set thresholds
  - **Settings** — provider chain, packs enabled, spend cap

**3.2** OpenAPI client generation
- Use `openapi-typescript` against FastAPI's existing schema
- Frontend gets fully-typed API calls for free

**3.3** Dark mode + brand polish
- Same shadcn token system DD uses
- Logo + colors TBD

**3.4** Streamlit kept as `mdi/ui/admin_streamlit.py` (renamed to signal "power-user view")

**Exit gate**: All 9 pages render and round-trip against a running FastAPI on localhost. No code in MDI's existing Python paths changes.

---

### Wave 4 — Cross-vertical proof (target: 1 week)

Goal: prove the platform is genuinely reusable by lighting up a NEW vertical that we haven't built for.

Recommended pick: **insurance** (DD already has a `configs/processing_insurance/policy_extraction.md` skeleton we can model from; it stretches MDI in a different direction than telecom invoices).

**4.1** New pack `mdi/packs/insurance/` matching the 13-slot pack contract
- Skills YAML, prompts, schema, classifier hints, content signals
- 4-6 synthetic golden seed documents (policy, claim, adjuster report, certificate of insurance)

**4.2** Run live eval on the new pack against real Gemini
- Confirm ≥80% accuracy without any code changes outside the pack directory
- That's the proof-of-reusability moment

**4.3** Telecom pack stub
- Mirror DD's `domain_packs.telecom` skeleton into `mdi/packs/telecom/`
- Don't port all 67 carriers — just enough (3-5) to show DD CAN be rehosted on MDI in the future

**4.4** Write up the case study
- New file: `docs/case-study-cross-vertical.md`
- "Same platform, 3 verticals, no platform code changed" — the marketing-ready artifact

**Exit gate**: Golden eval shows ≥5 packs passing target including the new insurance pack.

---

## Risks + mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Vertex AI auth complexity (ADC / service accounts) wastes a day | Medium | Keep AI-Studio path as fallback; ship Vertex as opt-in |
| Auto-pack registry generates noise (low-quality vendor stubs) | Medium | DD's blocklist + min-length filter; require explicit "promote" before stub influences extraction |
| Langfuse adds 3 containers to docker-compose; CI gets heavier | Low | Self-hosted Langfuse is optional, off by default — CI doesn't run it |
| Next.js replatform stalls in UI polish | High | Wave 3 ships *function-complete* but ugly; design polish is a separate ticket |
| Insurance pack eval underperforms | Medium | Synthetic goldens, so we can adjust prompts iteratively. Worst case → demo the framework with the existing packs |

---

## Confirmed scope (2026-06-04, post-review with Hari)

Decisions:
- Waves ship 1 → 2 → 3 → 4 in strict sequence.
- Frontend: reuse DD's Next.js + shadcn/ui structure as-is (JCP AI launch parity).
- Auto-registry promotion: keep explicit approval but make it a **one-click promote** in the UI.
- Wave 4 vertical: insurance, **target 90% golden accuracy**.
- Observability: self-hosted Langfuse for now; LangSmith deferred.

Additions from the review (fold into the relevant wave):

### Addition A — VLM (vision) as a first-class processing path *(Wave 1)*
Some documents need a Visual Language Model, not a text LLM — scanned PDFs, image-heavy layouts, signature blocks, table-as-image. `IngestedDocument.needs_vision` already exists in the schema; what's missing is a routed VLM provider. The new Vertex provider (W1.1) gains a `vision_extract(image_bytes, prompt)` method; Claude provider gets the same. Eyes flips `needs_vision: true` for scans (already done today via mime/heuristics); Hands picks the vision path automatically when the flag is set. Anthropic's Claude Sonnet vision is the secondary fallback for Gemini-Vision outages.

### Addition B — Multi-pattern recognition + web-browsable pattern store *(Wave 2 + Wave 3)*
Today a document matches one Hippocampus pattern (top cosine hit). Real documents often look like *several* patterns simultaneously (telecom invoice + contract attached + amendment notice). The Hippocampus retrieval already returns scored neighbours — we just need to keep more than the top hit and let downstream organs see all matches above threshold. Each match carries a contribution weight; Conscience + Insight Cortex see the union. The Patterns page in Wave 3 surfaces every learned pattern as a browsable card — schema preview, sample documents, anchor fields, last-seen, confidence — so analysts can audit what the brain has learned.

### Addition C — Code bridge: patterns → registered Python handlers *(Wave 2 + Wave 3)*
Extend Conscience's rule mechanism: a pattern (or a finding from a detector) can carry an optional `handler_id` string. The platform looks the id up in a `mdi/handlers/` registry of vetted Python callables and runs the handler with the document context. Handlers are loaded from a sandboxed allow-list (not eval'd from YAML — that's the simpleeval line), so adding a new handler is a code change reviewed in PR. Two ways analysts use this: (1) a learned pattern auto-attaches a known handler (e.g. "verizon_tax_recompute" handler runs on the Verizon-invoice pattern); (2) the chat layer or the new Commands page in Wave 3 lets an analyst issue a natural-language command that the platform maps to a handler (via the LLM's tool-use loop). The hardcoded Python remains the source of truth — the LLM is the dispatcher, not the executor.

---

## Updated wave outline (deltas from the original)

- **Wave 1** now ships **Vertex + Vision providers together** (was Vertex-only).
- **Wave 1.2** auto-pack registry: write stubs immediately, but they require a **one-click promote** from the Review page before they influence extraction.
- **Wave 2** now adds **multi-pattern retrieval** (return top-N above threshold, not top-1) and the **handler registry + code bridge**.
- **Wave 3** (revised 2026-06-04, Hari): the original 9-11 flat pages are consolidated to **3 routes + 1 chat drawer**. The natural workflow ("upload → see results → review") is one page stacked top-to-bottom (Workspace); learned state (Patterns + Tenant Facts + Auto-packs + Handlers) is one page with tabs (Brain); platform admin (Spend + Tenants + Settings) is one page with tabs (Admin). Chat lives as a slide-in drawer accessible from any route — asking the brain a question never warrants a route change.
- **Wave 4** target lifted to **90%** golden accuracy on insurance.

---

## Original open questions — answered

1. ~~Wave priority~~ → strict 1→2→3→4 sequence.
2. ~~Frontend stack~~ → Next.js 16 + shadcn/ui, reuse DD structure.
3. ~~Auto-registry promotion~~ → explicit approval, one-click UI.
4. ~~Vertical pick~~ → insurance, 90% target.
5. ~~Observability~~ → self-hosted Langfuse.
