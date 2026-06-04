# MDI as a reusable module

This file documents how to consume MDI as a **library** from another
codebase — the answer to "let's make this a generic, reusable function
across multiple projects." MDI ships as a Python package; downstream
projects import it the same way they would import `requests` or `fastapi`.

There are three integration shapes. Pick whichever fits your project:

| Shape | What it gives you | When to use it |
|---|---|---|
| **A. Library import** | Direct Python access to organs, orchestrator, schemas | Internal tools, batch jobs, CLIs |
| **B. REST client** | Hit MDI's FastAPI from any language | Web apps, mobile, multi-language stacks |
| **C. Forked pack** | Custom vertical bundled in your repo | You own a domain (telecom, healthcare) and need versioned schemas |

---

## A. Library import — Python projects

### Install

```bash
# From a sibling checkout
pip install -e ../mdi

# Or as a git dependency (private repo)
pip install "mdi @ git+ssh://git@github.com/yourorg/mdi.git@v0.1.0"
```

### Bootstrap (one-time per process)

```python
# yourproject/llm_setup.py
from mdi.kernel.llm_gateway import set_gateway, LLMGateway, CostTracker
from mdi.kernel.providers import GeminiProvider, AnthropicProvider  # noqa: F401 — registers

# Construct your own gateway with a custom CostTracker (e.g. lower cap for dev).
set_gateway(LLMGateway(cost_tracker=CostTracker(daily_cap_usd=2.00)))
```

### Process documents

```python
import asyncio
import uuid
from mdi.orchestrator.pipeline import run_batch_async

async def process(files):
    payloads = [{"filename": f.name, "content": f.read_bytes()} for f in files]
    return await run_batch_async(
        tenant_id=str(uuid.uuid4()),  # one tenant per consuming app/customer
        payloads=payloads,
        persist=False,                # toggle to True once Postgres is wired
    )

report = asyncio.run(process(my_files))
print(report["narrator_summary"])
for insight in report["insights"]:
    print(f"[{insight['severity']}] {insight['title']}")
```

### Single-organ embedding (when you don't need the full pipeline)

```python
from mdi.kernel.ingest import ingest
from mdi.brain import eyes, hands, conscience
from mdi.brain.hippocampus import baseline_rules_from_schema

doc = ingest("invoice.pdf", path.read_bytes())
cluster = await eyes.classify(doc)                      # just classification
schema = await pattern_cortex.discover(doc, cluster)    # just schema discovery
extraction = await hands.extract(doc, cluster, schema, corrections=[])
result = conscience.validate(extraction, baseline_rules_from_schema(schema))
```

Every organ is independently importable. The orchestrator is *one* way to
glue them; it's not the only way.

---

## B. REST client — non-Python projects

### Run the API

```bash
docker compose up -d                  # postgres + redis
alembic upgrade head
mdi-api                               # http://localhost:8080
```

### Authenticate

Issue a per-tenant API key once at provisioning time (see `src/mdi/kernel/auth.py::generate_api_key`)
and store its hash in the `api_keys` table. Then every request includes
either of:

```http
X-API-Key: mdi_<your-token>
# or
Authorization: Bearer <your-jwt>
```

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/process` | multipart files → BatchReport JSON |
| `GET` | `/report/{batch_id}` | fetch a previously-run batch |
| `POST` | `/chat` | conversational Q&A (graph-routed for relationship questions) |
| `POST` | `/correction` | submit an analyst correction (powers the self-improvement loop) |
| `GET` | `/tenant/usage` | spend + cap status |
| `GET` | `/health` | liveness |

### TypeScript example

```ts
const res = await fetch("http://api.example.com/process", {
  method: "POST",
  headers: { "X-API-Key": process.env.MDI_API_KEY! },
  body: formData,
});
const report = await res.json();
```

---

## C. Forked pack — when you own a vertical

A pack is a directory of YAML + Markdown that specifies the schema,
prompts, validators, and golden seed for one industry. Open-vocabulary
mode is the default, so packs are **opt-in**.

```
yourorg-pack/
├── skills.yaml              # the manifest
├── schema/
│   ├── fields.yaml
│   └── doc_types.yaml
├── prompts/
│   ├── invoice.md
│   └── ...
├── rules/
│   ├── validators.yaml
│   ├── merge.yaml
│   └── compliance.yaml
└── classifier/
    └── signals.yaml
```

To activate for a tenant:

```sql
UPDATE tenants
   SET pack_slug = 'telecom_billing'
 WHERE slug = 'big-telco';
```

The pack loader (`mdi.kernel.pack_loader`) finds packs in
`src/mdi/packs/<slug>/` by default; pass `packs_dir=` to load from your
own checkout.

---

## Multi-project patterns

### Scenario 1 — One codebase, many customers

This is the design path. Each customer = one row in `tenants`, isolated
by Postgres RLS. The same Python deployment serves N customers; chat,
patterns, corrections, and KG are per-tenant by construction.

```
┌─────────────┐     ┌──────────┐
│ Customer A  ├────►│          │     ┌────────────────┐
├─────────────┤     │ MDI API  ├────►│ Postgres + RLS │
│ Customer B  ├────►│          │     └────────────────┘
├─────────────┤     │          │
│ Customer C  ├────►│          │
└─────────────┘     └──────────┘
```

### Scenario 2 — Many codebases, shared brain

A finance app, a procurement app, and a contracts app all want to extract
data. Run MDI as one service; each app is a tenant. The brain is *shared
infrastructure*; the apps own the UI and the workflow.

### Scenario 3 — Embedded brain, no API

For tools that already have their own auth and storage, pull in MDI as a
library (path A above) and skip the API + Postgres entirely:

```python
from mdi.orchestrator.pipeline import run_batch_async

# In-process call. persist=False → no DB writes.
report = await run_batch_async(
    tenant_id="00000000-0000-0000-0000-000000000001",
    payloads=[...],
    persist=False,
)
```

Memory and KG are then ephemeral — fine for batch jobs that don't need
self-improvement across runs.

---

## Provider configuration

MDI is provider-agnostic via `kernel/provider_router.py`. Set in `.env`:

```env
GOOGLE_API_KEY=...        # Gemini Flash + Pro
ANTHROPIC_API_KEY=...     # Claude Haiku + Sonnet + Opus (optional)
DEFAULT_PROVIDER=auto     # 'auto' | 'gemini' | 'anthropic'
```

### Locked routing policy (Hari, 2026-05-07)

```
perception:  Gemini Flash  →  Claude Haiku    (cheap fallbacks for cheap calls)
extraction:  Gemini Flash  →  Claude Sonnet   (vision-capable fallback)
reasoning:   Gemini Pro    →  Claude Opus     (rule-invention quality)
synthesis:   Gemini Pro    →  Claude Opus     (narrator/chat polish)
```

The first column is **primary** — every call starts there. The arrow
fallback only fires when the primary errors on a retryable category
(rate limit, 5xx, timeout, network, missing API key). If both fail, the
original exception is re-raised.

### What does NOT trigger fallback

- 4xx client errors (auth, malformed request, model-not-found) — would
  fail identically on the fallback, so we surface them immediately.
- Budget exceeded — never even tries the call.
- The user-supplied `provider=`+`model=` shorthand — explicit wiring is
  treated as "I know what I want", no fallback chain.

### Cost behaviour

When fallback fires, that day's bill climbs onto Claude. The
`cost_events` table records each call with its actual provider+model;
filter by provider to see the fallback rate. A spike is the canary for
"Gemini is having a bad hour" — wire an alert on it.

### Changing the policy

Per-organ tier mapping lives in `provider_router._POLICY`. Edit the
dict-of-lists; ordering is meaningful (index 0 is primary). The unit
tests `test_provider_router.py` and `test_gateway_routing.py` will
exercise your edit.

---

## Versioning

The package version (`pyproject.toml::project.version`) advances only on
**contract** changes — schema additions, API changes, organ output shape.
Internal changes are not version-bumps. Pin to a specific version in
downstream `pyproject.toml`:

```toml
dependencies = ["mdi==0.1.0"]
```

Pack versions are independent — a pack ships its own `version: 1.0.0`
and the pack loader records that on every batch.

---

## Operational notes

- **Cost ceilings travel with the gateway, not with the API.** If you
  spawn multiple gateway instances in one process, each gets its own
  CostTracker. Use a single shared `LLMGateway` per process.
- **Embeddings are heavy.** `BAAI/bge-m3` is ~2GB. Tests pass
  `use_real_embeddings=False` to avoid the load. Production should
  warm the model once at boot.
- **RLS policies fail closed.** If `current_setting('app.tenant_id')`
  is unset, no rows are visible. Always go through `tenant_session()`.

### The two-role DB pattern (PRODUCTION REQUIRED)

Postgres superusers and roles with `BYPASSRLS` skip row-level security
**unconditionally** — even with `FORCE ROW LEVEL SECURITY`. The default
`POSTGRES_USER` from the official postgres image is a superuser.

You **must** create a non-superuser application role and route runtime
queries through it. Otherwise your tenant isolation is silently disabled
and you'll only catch it with a two-tenant integration test (which is
why we ship one).

```sql
-- Run as the superuser ONCE per database after migrations.
CREATE ROLE mdi_app LOGIN PASSWORD 'change-me' NOSUPERUSER NOBYPASSRLS;
GRANT USAGE ON SCHEMA public TO mdi_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO mdi_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO mdi_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO mdi_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO mdi_app;
```

Then point `DATABASE_URL` and `DATABASE_URL_ASYNC` at `mdi_app`. Keep
the superuser DSN in something like `DATABASE_URL_ADMIN` for alembic
and ad-hoc admin work.

### `tenant_session()` semantics

The GUC is set with `is_local=False` (session-scoped, not
transaction-scoped). Reason: the orchestrator commits mid-pipeline, and
a transaction-scoped GUC would evaporate at the first commit, leaving
subsequent reads unfiltered. We reset the GUC on session exit so pooled
connections don't carry tenant context across requests.
