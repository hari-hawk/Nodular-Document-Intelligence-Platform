# MDI Gap Analysis — 2026-05-13

Honest assessment of what's done, what's missing, and what to build next.
Inputs: synthesis document, locked decisions in CLAUDE.md, 6 days of live
testing on Gemini + Claude with a real Postgres + RLS stack.

---

## Where we are (validated end-to-end)

| Capability | Status | Evidence |
|---|---|---|
| 7 brain organs (Eyes, Pattern Cortex, Hands, Conscience, Hippocampus, Inner Voice, Insight Cortex) | ✅ functional | 44/44 offline tests + live cross-industry corpus |
| 7 supporting layers (Coverage, Account Briefing, Narrator, Chat, KG, Graph Builder, Entity Resolver) | ✅ functional | same |
| 19-stage pipeline | ✅ wired | progress events confirm stages 1–16 fire; stages 17–19 fire when persist=True |
| Multi-tenant via Postgres RLS | ✅ verified | two-tenant isolation test green via `mdi_app` non-superuser role |
| Gemini provider (Flash + Pro) | ✅ live | model pings returned `pong` for Flash and Pro |
| Anthropic provider (Haiku, Sonnet, Opus) | ✅ live | model pings returned `pong` for all three |
| Tier-based provider routing + fallback chain | ✅ proven | empty Gemini key → Claude served all 4 organ calls correctly |
| Cost tracking (daily cap + soft warn + hard cap) | ✅ working | tracked $0.10 across this week's live tests |
| Cross-industry classification (telecom / healthcare / legal / cloud) | ✅ proven | 5/5 docs classified into 4 distinct industries |
| Pattern memory (self-improvement loop) | ✅ proven | 67% per-doc cost reduction on memory hit |
| Knowledge graph (Postgres-backed, 12 node types, 11 edge types) | ✅ persisting | 14 nodes / 12 edges after 7 docs |
| Streamlit analyst UI | ✅ running | localhost:8501, 7 tabs |
| Excel + CSV export | ✅ working | Results tab downloads `.xlsx` and `.csv` |

---

## Where we have known gaps

Ranked by impact + likelihood-to-bite-us.

### Gap 1 — No per-stage evaluation (silent degradation risk) — **HIGH**
Every organ trusts the LLM blindly. If Gemini quietly degrades on a particular
doc type (confidence drops, fields go null, JSON shape changes), nothing alerts
us. The eval harness exists for end-to-end accuracy against golden datasets, but
**there's no per-stage quality gate**.

**Fix:** EvalLayer — one per organ, runs after the organ, attaches a
`StageEvalResult` to the BatchReport. Surfaces in the UI as red/yellow/green badges.

### Gap 2 — Chat synthesis lacks document retrieval (RAG missing) — **HIGH**
Today Chat routes relationship questions to the KG (works great) and synthesis
questions to Gemini Pro with only KG centrality as context. So a question like
*"what are the renewal terms in my contracts?"* gets a vague answer because the
LLM never sees the actual contract text.

**Fix:** Document-chunk RAG sidecar. Chunk each doc on ingest, embed with bge-m3,
store in a new `doc_chunks` table with pgvector. On chat queries, retrieve top-K
chunks by cosine similarity and inject as additional system context.

### Gap 3 — Pattern duplication on parallel writes — MEDIUM
Two docs in the same batch with identical `(industry, vendor, doc_type)` each
write a new `patterns` row instead of upserting. We saw this last turn — 6
patterns persisted, 2 of which were `(telecom, AT&T, invoice)` duplicates.

**Fix:** Convert `write_pattern` to `INSERT … ON CONFLICT (tenant_id, industry,
vendor, doc_type) DO UPDATE SET …`. Requires a uniqueness constraint migration.

### Gap 4 — Limited export formats — MEDIUM
Current: CSV, Excel. Customers ask for: PDF (executive summary or detailed
per-doc), email-ready HTML, JSON (raw BatchReport), .eml file.

**Fix:** Multi-format export module. PDF via `reportlab`, email via inline-CSS
HTML + optional `.eml` packaging.

### Gap 5 — Entity Resolver not wired into Graph Builder — MEDIUM
`AT&T` and `AT&T Business Services` are separate KG nodes today, even though
both should resolve to one canonical Vendor. The Entity Resolver exists
(rapidfuzz at 85%) but Graph Builder doesn't call it on canonicalization.

**Fix:** Pre-resolve `canonical_key` through the Entity Resolver before
`upsert_node`. Surface auto-merges in the audit log; review-tier merges go
into an `entity_review` queue.

### Gap 6 — No outlier-triggering corpus for Insight Cortex — LOW
Insight Cortex's heuristics fire on ≥15% deviation from trailing median; our
test corpus has only smooth-trending invoices, so 0 insights ever fire.

**Fix:** Add a sample doc with a deliberate outlier (e.g. invoice with 2×
normal spend) to the corpus. Mostly a test-data issue, not a code issue.

### Gap 7 — No live_llm pytest harness — LOW
Cross-industry + memory-hit demo is currently a one-shot manual script. Should
be a `pytest -m live_llm` test that runs on demand against real APIs.

**Fix:** Convert the ad-hoc demo scripts into pytest fixtures + tests gated by
the `live_llm` marker (already declared in `pyproject.toml`).

### Gap 8 — Field name drift only patched in UI — LOW
Gemini calls totals `total`; Claude calls them `total_amount`. Our `_normalize_field_name`
map lives in the Streamlit code. That means programmatic API consumers see raw
LLM-emitted names, but Streamlit users see normalized ones — inconsistent.

**Fix:** Move normalization into Hands extraction (post-process before persisting),
so all downstream consumers see canonical names.

### Gap 9 — No tenant onboarding flow — LOW
Tenant creation today is a manual SQL `INSERT INTO tenants`. Customer onboarding
requires a UI/API path that also generates an API key.

**Fix:** Add `/admin/tenant` endpoint + Streamlit admin page. Phase 4 Week 7
deliverable per synthesis doc.

### Gap 10 — Audit query interface — LOW
The `audit_log` table populates, but there's no UI for "who corrected field X
on doc Y between dates A and B?". Required for compliance customers.

**Fix:** Add an `Audit` tab to Streamlit with filterable query.

---

## What this turn ships

Closing **Gaps 1, 2, 4** in priority order:

1. **EvalLayer framework** + per-stage evaluators wired into the pipeline.
2. **RAG layer** for Chat synthesis (doc_chunks table + chunker + retriever).
3. **Multi-format exports** (PDF, Email-HTML, JSON) alongside the existing CSV + Excel.

Carrying Gaps 3, 5–10 to the next turn unless explicitly re-prioritized.

---

## Locked: still local-only, no cloud

Per direction: stay on local Postgres + Redis (docker-compose) until the
platform is happy on the existing reference repo's behaviour. Cloud setup
(Vertex AI swap, hosted Postgres, hosted Redis) deferred to a later phase.
Gemini API key handles primary inference; Anthropic API key handles fallback.
Both are in `.env` and gitignored.

---

## RAG decision — why we need it, what it does NOT replace

| Layer | Pattern memory (existing) | Document RAG (new) |
|---|---|---|
| Purpose | Recognize that a new doc looks like a doc-type we've seen before, reuse the schema and rules | Answer chat questions grounded in actual document content |
| Retrieval unit | Cluster `(industry, vendor, doc_type)` | Text chunks (~512 tokens each) |
| Embedding scope | One vector per pattern | Many vectors per document |
| Read latency | Sub-100ms (HNSW + scope filter) | ~50–100ms top-K=8 |
| Write latency | One row per pattern when written | N rows per doc (chunks) |
| When it fires | Stage 3 of the pipeline (memory check) | Inside Chat layer when route=synthesis |
| What it replaces | — (was always there) | — (was relying on KG centrality only) |

Both layers use pgvector. Pattern memory lives in `patterns.embedding`; chunks
will live in `doc_chunks.embedding`. They're complementary, not overlapping.
