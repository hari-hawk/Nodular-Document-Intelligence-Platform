# MDI — Platform Overview

**Modular Data Intelligence** — a self-learning document brain that turns
unstructured documents (invoices, contracts, claims, certificates, statements)
into structured, auditable data.

> **One line**: *Upload any document → the brain reads it, extracts every
> field, learns the pattern, and gets smarter for the next one.*

---

## Part A — For Business Stakeholders

### The problem we solve

Every business receives documents from many vendors in many formats. Each
one needs structured data extracted — vendor, account, dates, totals, line
items, terms. Today this happens via manual data entry, per-vendor templates
that break the moment a layout changes, or rigid OCR rules that don't
generalise. **MDI replaces all of that with a learning document brain.**

### How it works (the simple version)

When you upload a document, the platform's "brain" does six things — and
remembers what it learned for next time:

| Stage | What happens (plain English) |
|---|---|
| 👁  **Eyes** | Looks at the document and identifies what it is (telecom invoice? insurance policy? purchase order?) |
| 🧠  **Memory** | Asks "have we seen something like this before?" If yes, reuses what it learned. If no, discovers a new pattern. |
| ✋  **Hands** | Reads out every field — vendor name, account, dates, amounts, line items, addresses, contract terms. |
| ⚖️  **Conscience** | Cross-checks the maths and flags anything suspicious (totals that don't add up, expired policies, missing fields). |
| 💡  **Insight Cortex** | Tells you what's interesting across the batch (recurring vendors, pricing outliers, contracts about to expire). |
| 📝  **Brain memory** | Stores the pattern so the **next** similar document is faster + more accurate. |

### Customer-facing flow (1 minute view)

```mermaid
flowchart LR
  A[1. Upload<br/>any document] --> B[2. Identify<br/>what is this?]
  B --> C[3. Extract<br/>read every field]
  C --> D[4. Review<br/>fix anything wrong]
  D --> E[5. Learn<br/>brain memorises<br/>your correction]
  E -.benefits future docs.-> B

  style A fill:#EEF2FF,stroke:#4F46E5,color:#1E1B4B
  style B fill:#EEF2FF,stroke:#4F46E5,color:#1E1B4B
  style C fill:#EEF2FF,stroke:#4F46E5,color:#1E1B4B
  style D fill:#EEF2FF,stroke:#4F46E5,color:#1E1B4B
  style E fill:#DCFCE7,stroke:#16A34A,color:#14532D
```

### What makes MDI different

| | Traditional OCR / templating | **MDI** |
|---|---|---|
| Setup per vendor | weeks of template authoring | **zero** — discovers on first sight |
| Layout changes | breaks silently | **adapts** automatically |
| Learning from corrections | no — manual rule edits | **yes** — corrections embed semantically and bias future extractions |
| Cross-vertical | one vertical per deployment | **one platform, many verticals** — packs add insurance / telecom / healthcare / manufacturing without code change |
| LLM down? | breaks entirely | **falls back** to deterministic regex (still extracts in 150 ms) |
| Multi-tenant | per-customer instances | **single platform**, customer data isolated by row-level security |
| Audit trail | partial / no provenance | **every value** carries the exact text snippet that drove it |

### Two-speed processing (you choose per upload)

| Mode | Path | Latency | When to use |
|---|---|---|---|
| ⚡ **Quick** | Parse + regex patterns | **~150 ms** per file | Immediate inspection, demos, LLM rate-limited, large batch screening |
| ✨ **Full** | Parse + LLM (Gemini/Claude) + insights + memory | **~30 s** per file | Production extraction with full coverage + insights + pattern memory |

Both produce the same output shape. You can run Quick first, then promote
individual documents to Full later via the "Re-extract" button.

### Where MDI sits in your stack

```mermaid
flowchart LR
  Source[Documents arrive<br/>email · folder · API · upload] --> MDI
  MDI[MDI Platform<br/>Document Brain]
  MDI --> ERP[ERP / Accounting]
  MDI --> CRM[CRM / Customer DB]
  MDI --> Audit[Audit / Compliance Storage]
  MDI --> BI[BI / Reporting]

  Corrections[Analyst Corrections] -.continuously learn.-> MDI

  style MDI fill:#6366F1,stroke:#312E81,color:#FFFFFF
```

---

## Part B — For Technical Architects

### Stack at a glance

| Layer | Technology | Reason |
|---|---|---|
| **API** | Python 3.11, FastAPI, async SQLAlchemy + asyncpg | Async-native, OpenAPI free, mature in fintech |
| **DB** | PostgreSQL 15 + pgvector + HNSW index | One engine for relational, vector ANN, audit log — minimises operational surface |
| **Tenant isolation** | PostgreSQL Row Level Security + non-superuser app role (`mdi_app`, NOBYPASSRLS) | Isolation enforced at the database, not in app logic. App bugs can't leak across tenants. |
| **Embeddings** | bge-m3 (1024 dim) via sentence-transformers | Open-weight, on-par with OpenAI ada-002, zero vendor lock-in |
| **LLM providers** | Gemini 2.5 (Flash + Pro) primary; Claude (Haiku/Sonnet/Opus) fallback | Cost-optimised primary + resilience fallback; same prompt contract via provider router |
| **VLM (vision)** | Gemini 2.5 Pro vision; Claude 3.5 Sonnet vision | Scanned PDFs route via `needs_vision: true` flag set by Eyes |
| **PDF / parsing** | pdfplumber, Docling | Text-mode + layout-aware modes |
| **Heuristic extractor** | Pure Python regex catalogue | Deterministic floor — works without any external service |
| **Observability** | Self-hosted Langfuse + structlog | Per-LLM-call trace UI, structured JSON logs |
| **Cost control** | CostTracker (in-memory daily) + SpendLedger (file-backed cumulative) | Hard cap + soft warn, raises before the API call |
| **Cache / queue** | Redis 7 | Celery broker + result backend |
| **Frontend** | Next.js 15 (App Router) + React 19 + Material UI 6 + Tanstack Query | Server-rendered hydration, accessible by default, customer-facing aesthetic |
| **Deployment** | docker-compose (dev) → containerised services (prod) | Single-command local dev; production-portable |
| **CI** | GitHub Actions — ruff + pytest + pgvector service | Lint + 160 offline tests + RLS-verified migration on every push |

### Layered architecture

```mermaid
flowchart TB
  subgraph FE[Frontend - Next.js 15 + MUI 6]
    Workspace[Workspace<br/>Upload · Results · Review]
    Brain[Brain<br/>Patterns · Facts · Auto-packs · Handlers]
    Admin[Admin<br/>Tenants · Spend · Settings]
    Chat[Chat Drawer<br/>RAG over corpus]
  end

  FE -->|/api/* proxied| API

  subgraph API[API Layer - FastAPI]
    Routes[Routes<br/>admin-or-tenant auth]
    Auth[RLS context<br/>set_config app.tenant_id]
  end

  API --> Orch

  subgraph Orch[Orchestrator - 19-stage pipeline]
    direction LR
    Ingest --> Eyes --> Hippo --> Pattern --> Hands --> Conscience --> Memory --> Insights --> Reflection --> Coverage --> Briefings --> Narrator --> Graph
  end

  Orch --> DB

  subgraph DB[Persistence - Postgres 15 + pgvector]
    Tables[tenants · documents · extractions<br/>patterns vec · doc_chunks vec · corrections vec<br/>tenant_facts · auto_pack_proposals<br/>audit_log · batches · cost_events]
    RLS[FORCE ROW LEVEL SECURITY<br/>tenant_isolation policy on every table]
  end

  Orch -.handlers.-> CB[Code-Bridge<br/>Registered Python plugins]
  Orch -.traces.-> LF[Langfuse<br/>self-hosted]
  Orch -.embed.-> Emb[bge-m3<br/>local model]

  style FE fill:#EEF2FF,stroke:#4338CA
  style API fill:#E0E7FF,stroke:#4338CA
  style Orch fill:#C7D2FE,stroke:#4338CA
  style DB fill:#FEF3C7,stroke:#92400E
```

### The 19-stage pipeline (full pipeline view)

```mermaid
flowchart TD
  U[POST /process<br/>multipart files] --> S1[1. Ingest<br/>pdfplumber → text/pages/images]
  S1 --> S2[2. Eyes - Classify<br/>LLM + content_signals shortcut<br/>industry · vendor · doc_type · confidence]
  S2 --> S3{3. Hippocampus<br/>memory check<br/>pgvector ANN cosine}
  S3 -- hit ≥0.82 --> S6
  S3 -- miss --> S4[4. Pattern Cortex<br/>LLM discovers schema<br/>+ pack augmentation]
  S4 --> S5[5. Conscience<br/>rule invention<br/>simpleeval expressions]
  S5 --> S6
  S6[6. Correction lookup<br/>exact + semantic ANN] --> S7
  S7[7. Hands<br/>LLM extract values<br/>+ canonical alias normaliser] --> S8
  S7 --> SQ{Quick mode?<br/>POST /process/quick}
  SQ -- yes --> HQ[Heuristic regex extractor<br/>~150ms total]
  HQ --> SX[Persist documents +<br/>extractions + batch]
  S8[8. Conscience validate<br/>simpleeval rules → anomalies] --> S9
  S9[9. Memory write<br/>UPSERT pattern by scope] --> S10
  S10[10. Insight Cortex<br/>LLM + deterministic detectors:<br/>recurring vendors · pricing anomalies ·<br/>contract expirations] --> S11
  S11[11. Inner Voice<br/>reflection on quality] --> S12
  S12[12-13. Coverage + groups<br/>cross-doc clustering] --> S14
  S14[14. Account briefings] --> S15
  S15[15. Narrator<br/>LLM summary prose] --> S16
  S16[16. BatchReport assembly] --> S17
  S17[17-19. Graph build · KG insights<br/>cross-doc validation] --> O[Return BatchReport<br/>+ persist]

  SX --> O

  style S3 fill:#FEF3C7
  style S6 fill:#FEF3C7
  style HQ fill:#DCFCE7
  style SQ fill:#FCE7F3
```

### Two-track extraction strategy

```mermaid
flowchart LR
  subgraph T1[⚡ Quick Track]
    Q1[Parse PDF text<br/>pdfplumber] --> Q2[Regex catalogue<br/>vendor · doc_no · dates ·<br/>amounts · payment terms]
    Q2 --> Q3[Persist + return<br/>~150ms total]
  end

  subgraph T2[✨ Full Track]
    F1[Parse + Eyes classify<br/>LLM call] --> F2[Schema discovery<br/>LLM + pack augment]
    F2 --> F3[Hands extract<br/>LLM + VLM]
    F3 --> F4[Conscience validate]
    F4 --> F5[Insights + memory write<br/>~30s total]
  end

  U[Upload] --> T1
  U --> T2

  T1 -.upgrade later<br/>via Re-extract button.-> T2

  style T1 fill:#DCFCE7,stroke:#16A34A
  style T2 fill:#E0E7FF,stroke:#4338CA
```

### Multi-tenant security model

```mermaid
flowchart LR
  C[Client request<br/>X-API-Key or X-Admin-Key] --> A{Auth resolver}
  A -- tenant key --> T[tenant_session<br/>SET app.tenant_id = uuid]
  A -- admin key --> AD[admin engine<br/>via mdi superuser]
  T --> Q1[Query under RLS<br/>policy filters to tenant]
  AD --> Q2[Cross-tenant query<br/>RLS bypassed]
  Q1 --> R[Response<br/>only this tenant's rows]
  Q2 --> R2[Response<br/>all rows + tenant_id per row]

  style T fill:#DCFCE7
  style AD fill:#FEE2E2
```

### Learning loop (self-training)

```mermaid
flowchart LR
  D1[New document arrives] --> E[Eyes classifies]
  E --> M{Hippocampus<br/>vector ANN}
  M -- match --> RU[Reuse schema + rules]
  M -- no match --> NP[New pattern]
  NP -.write to pgvector.-> M
  RU --> X[Extract values]
  NP --> X
  X --> R[Analyst reviews in UI]
  R -- correct value --> C[Embed correction<br/>to pgvector + persist]
  C -.bias future extracts.-> X
  X --> O[Output structured data]

  style M fill:#FEF3C7
  style C fill:#DCFCE7
```

### Brain memory subsystems

| Subsystem | Stores | Where | Used for |
|---|---|---|---|
| **Hippocampus patterns** | Schema + rules per `(industry, vendor, doc_type)` | `patterns` table, `vector(1024)` | Skip schema discovery on next similar doc |
| **Tenant facts** | Stable per-customer truths (account→vendor, contract→expiry) | `tenant_facts` table | Cross-batch persistent knowledge |
| **Corrections** | Analyst edits with embedded context sentence | `corrections` table, `vector(1024)` | Bias future extractions toward analyst-approved values |
| **Auto-pack proposals** | Newly-discovered vendors awaiting curation | `auto_pack_proposals` | One-click pack creation; explicit promotion |
| **Handler registry** | Vetted Python callables triggerable by chat / patterns | In-process registry | Code-bridge — LLM dispatches but never executes |

### Key design decisions + reasoning

| Decision | Reason |
|---|---|
| **Open-vocabulary schema** (not fixed templates) | Vendor layouts change constantly; rigid templates need maintenance. Pattern Cortex discovers fields per-document via LLM; the canonical-alias layer keeps names stable downstream. |
| **RLS + non-superuser app role** | Tenant isolation enforced at the DB. App bugs cannot leak cross-tenant data. Verified at every migration via `FORCE ROW LEVEL SECURITY`. |
| **Two-engine DB pool** | App routes use `mdi_app` (NOBYPASSRLS). Admin cross-tenant routes use `mdi` (superuser, bypasses RLS). Separate pools prevent accidental scope creep. |
| **Provider fallback chain** | Gemini is cheap but rate-limits. Claude is the resilience layer. Same prompt contract; the router walks the chain on retryable errors. |
| **Heuristic extractor as Quick mode** | LLM availability is never 100%. Regex floor gives an always-on path. Production-grade docs (Georgetown invoices) extract 6 fields in 150 ms with `source_text` provenance. |
| **pgvector instead of a separate vector DB** | One DB to operate + backup + secure. HNSW scales to millions of vectors. Cross-table joins (extractions ↔ patterns) stay relational. |
| **Pack abstraction** (YAML, no Python) | Adding a vertical is a config commit, not a code release. Pack augmentation in Pattern Cortex unifies LLM discovery + pack-declared fields. |
| **Per-value provenance** (`source_text`) | Every extracted field carries the substring that drove it. Audit + compliance + analyst trust. |
| **Self-hosted Langfuse** | Trace every LLM call without sending prompts / customer data to a 3rd-party cloud. |
| **8px grid + WCAG AA** | Accessibility by design. MUI Material 3 tokens default-compliant. |
| **MUI + Tailwind side-by-side** | MUI for the polished primitives that need accessibility-out-of-the-box (Drawer, Table, Dialog). Tailwind for everything else. Emotion + Tailwind don't conflict at runtime. |

### API surface (what the UI calls)

| Route | Purpose |
|---|---|
| `POST /process` | Full 19-stage LLM pipeline |
| `POST /process/quick` | Heuristic-only fast lane (~150 ms / file) |
| `GET /batches` | Recent batches (admin-or-tenant auth) |
| `GET /report/{id}` | Full BatchReport for a batch |
| `GET /admin/documents/{id}/text` | Raw parsed text per document |
| `POST /admin/documents/{id}/extract-heuristic` | Re-run regex extractor on persisted doc |
| `POST /correction` | Analyst correction → pgvector embedding |
| `GET /admin/patterns` + `/{id}` | Memorised pattern explorer |
| `GET /admin/tenant-facts` | Per-tenant master data |
| `GET /admin/auto-packs` + `/{id}/promote` | Auto-discovered vendor proposals |
| `GET /admin/handlers` + `/{id}/run` | Code-bridge plugins |
| `POST /chat` | RAG over the tenant's corpus |
| `GET /admin/spend` | Cumulative LLM spend ledger |

### Operational characteristics

| Metric | Target | Today |
|---|---|---|
| Quick-mode latency | < 500 ms / file | ~150 ms |
| Full-mode latency (LLM up) | < 60 s / file | ~30 s |
| Backend offline tests | green | **160 / 160** |
| Ruff lint | clean | clean |
| Bundle size (first-load JS) | < 250 kB | ~200 kB across all routes |
| Tenant isolation | RLS-enforced | yes + `FORCE ROW LEVEL SECURITY` |
| Provider fallback | automatic | Gemini → Claude via router |

---

## Sharing this document

- **For executives + buyers**: share Part A above (mermaid renders as inline diagrams in any markdown viewer).
- **For technical architects**: share Part B (the layered diagram + pipeline diagram + decision table cover the core architecture; the API table maps directly to what the UI consumes).
- **GitHub / Notion / Confluence**: all three render Mermaid natively — paste this file in and the diagrams will appear.
- **PDF export**: `pandoc PLATFORM_OVERVIEW.md -o overview.pdf` produces a print-ready handout.

---

*Last updated: 2026-06-05 · Maintained at `mdi/docs/PLATFORM_OVERVIEW.md`.*
