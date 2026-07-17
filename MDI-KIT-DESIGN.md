# MDI Kit — Design Contract

**Status**: v1 committed · **Owner**: MDI core team · **Last updated**: 2026-06-05

This is the design contract for `mdi-kit` v1. It defines the public API, CLI,
run modes, provider configuration, pack registry, repository layout, and
migration path from the existing platform. Engineering builds against this
document; product/stakeholder framing lives in
[`documents/platform-overview.html`](documents/platform-overview.html) Part D.

---

## 1. Purpose

`mdi-kit` is a Python library that packages MDI's document-extraction pipeline
as a consumer-facing SDK. Any project team in the org can:

```python
from mdi_kit import Brain
brain = Brain(pack="finance/invoice_v1", filters=["vendor", "amount_due"])
result = brain.extract("invoice.pdf")
```

…and get structured JSON with confidence + provenance, without setting up a
platform, running a database, or managing LLM keys in their app code.

The library exists because multiple project teams currently reinvent
document-extraction pipelines independently. `mdi-kit` collapses that
duplicated effort into a single well-maintained module.

---

## 2. Design principles

These principles decide every close call in v1:

1. **Consumer time-to-first-extraction is the north-star metric.**
   ≤ 10 lines of Python from `pip install` to structured output. If a
   feature adds lines to a consumer's code, it must justify itself.
2. **Packs are the primary user interface.** Teams pick from a curated set
   of packs; they don't write extraction code. Custom packs live in YAML,
   not Python.
3. **Kit runs where the consumer runs.** No mandatory hosted service.
   No data leaves the consumer's environment unless they explicitly
   configure an LLM provider that does (Vertex, Claude via Bedrock).
4. **Stateless is the default; stateful is opt-in.** Most consumers want
   extract-and-forget. Learning is a feature they enable when they're
   ready to manage a Postgres.
5. **Per-project brain isolation in v1.** No cross-project data leakage.
   Shared brain is a v2 conversation once we have compliance sign-off.
6. **The gateway abstraction survives.** Existing multi-provider LLM
   router (Vertex → Claude fallback) stays. Kit adds a Vertex adapter,
   does not replace the gateway.
7. **Git is the pack registry.** Packs are YAML; git already handles
   versioning, code review, rollback. Don't build a registry service.

---

## 3. Public API surface

### 3.1 `Brain` — the primary entry point

```python
class Brain:
    def __init__(
        self,
        *,
        pack: str | None = None,
        filters: list[str] | None = None,
        provider: ProviderConfig | None = None,
        mode: Literal["stateless", "stateful"] = "stateless",
        storage: StorageConfig | None = None,
        project_id: str | None = None,
        langfuse: LangfuseConfig | None = None,
    ) -> None: ...

    def extract(
        self,
        source: str | Path | bytes | BinaryIO,
        *,
        overrides: dict[str, Any] | None = None,
    ) -> ExtractResult: ...

    def extract_batch(
        self,
        sources: Iterable[str | Path | bytes | BinaryIO],
        *,
        max_workers: int = 4,
    ) -> Iterable[ExtractResult]: ...

    def close(self) -> None: ...

    # Context-manager support so callers can `with Brain(...) as b:`
    def __enter__(self) -> "Brain": ...
    def __exit__(self, *exc: Any) -> None: ...
```

**Constructor rules:**
- `pack` xor `filters` may be omitted, but at least one must be provided —
  otherwise the Brain has nothing to extract.
- `pack` accepts `"finance/invoice_v1"` (name only, latest) or
  `"finance/invoice_v1@2.3"` (pinned version).
- `filters` is a subset (or superset via composition — see §3.3) of the
  pack's fields. If a filter names a field the pack doesn't define,
  the kit raises `UnknownFieldError` at construction time, not extract time.
- `provider` defaults to `VertexProvider()` if not given; falls back to
  `ClaudeProvider()` on retryable errors.
- `mode="stateful"` requires `storage` to be set.
- `project_id` is used for Langfuse tagging + optional metric attribution.
  Auto-generated (UUID) if omitted.

### 3.2 `ExtractResult` — the return type

```python
@dataclass(frozen=True)
class ExtractResult:
    document_id: str                           # UUID for this extraction
    fields: dict[str, Any]                     # {field_name: value}
    confidence: dict[str, float]               # {field_name: 0.0-1.0}
    source_text: dict[str, str]                # {field_name: exact string from doc}
    pattern_matched: str | None                # if Hippocampus hit, else None
    route: Literal["heuristic", "llm", "vlm"]  # which extraction lane won
    anomalies: list[Anomaly]                   # Conscience flags
    elapsed_ms: int                            # wall-clock
    cost_usd: float                            # 0.0 for heuristic, ~$0.01-0.20 for LLM
    raw: dict[str, Any]                        # for debugging / migration
```

`ExtractResult` is frozen so callers can safely cache/serialize.
The `raw` dict is a stable-shape escape hatch for teams that need
data the typed fields don't expose (metadata, per-page confidence, etc.)
— we won't break backwards compat on `raw` keys within a major version.

### 3.3 `Pack` and filter composition

```python
class Pack:
    """Loaded pack — schema + prompts + validators + enrichment."""

    @classmethod
    def load(cls, name: str) -> "Pack": ...             # from registry
    @classmethod
    def from_yaml(cls, path: Path) -> "Pack": ...       # from local file

    name: str
    version: str
    fields: dict[str, FieldSpec]
    prompts: dict[str, str]                             # by doc_type
    validators: list[ValidatorSpec]
    enrichment: dict[str, dict[str, str]]

    def compose(
        self,
        *,
        include: list[str] | None = None,
        exclude: list[str] | None = None,
        add: list[FieldSpec] | None = None,
    ) -> "Pack": ...                                    # returns a new Pack
```

Composition example — team wants a subset of the contract pack + one
extra custom field:

```python
from mdi_kit import Brain, Pack

base = Pack.load("legal/contract_v1")
composed = base.compose(
    include=["parties", "effective_date", "termination_date"],
    add=[FieldSpec(name="internal_matter_id", type="string", required=False)],
)
brain = Brain(pack=composed)
```

### 3.4 `ProviderConfig` — LLM adapters

```python
class ProviderConfig(Protocol):
    """Kit-side interface. Wraps the existing llm_gateway."""

@dataclass
class VertexProvider(ProviderConfig):
    project: str                                        # GCP project ID
    location: str = "us-central1"
    model: str = "gemini-2.5-flash"
    service_account_path: Path | None = None            # else ADC
    fallback: ProviderConfig | None = None              # default: ClaudeProvider()

@dataclass
class ClaudeProvider(ProviderConfig):
    api_key: str | None = None                          # else env ANTHROPIC_API_KEY
    model: str = "claude-3-5-sonnet-20241022"
    via_bedrock: bool = False                           # True → AWS Bedrock

@dataclass
class NullProvider(ProviderConfig):
    """No LLM — heuristic regex only. Useful for tests + air-gapped envs."""
```

**Provider selection rules:**
- `Brain(provider=None)` → `VertexProvider()` with ADC + `ClaudeProvider()` fallback
- Consumer can pass any `ProviderConfig`; kit calls it via the internal gateway
- `NullProvider` short-circuits everything after heuristic extraction — always-on
  path for teams that can't send data outside their VPC

### 3.5 `StorageConfig` — stateful mode

```python
@dataclass
class PostgresStorage:
    dsn: str                                            # postgresql+asyncpg://...
    schema: str = "mdi_kit"
    auto_migrate: bool = True                           # run schema migrations on init
    enable_rls: bool = True                             # force row-level security

@dataclass
class InMemoryStorage:
    """Stateless / ephemeral — no learning across extractions."""
```

**Rules:**
- `mode="stateful"` requires `PostgresStorage`. Auto-migrates the schema on
  first use if `auto_migrate=True`.
- Storage is scoped by `project_id` — no cross-project reads or writes even
  if two projects share the same Postgres.
- pgvector extension required; kit checks on init and raises a clear error
  with the `CREATE EXTENSION` command if missing.

### 3.6 `LangfuseConfig` — observability

```python
@dataclass
class LangfuseConfig:
    host: str                                           # https://langfuse.internal
    public_key: str
    secret_key: str
    project_tag: str | None = None                      # auto-tags every trace
```

If omitted, kit runs without Langfuse. If set, every LLM call is traced
with `project_id`, `pack`, and `document_id` tags for filterable analytics.

---

## 4. CLI

Installed as `mdi-kit` when the package is installed. All commands accept
`--json` for machine-readable output.

```
mdi-kit --version
mdi-kit --help

# Extraction
mdi-kit extract <FILE>                              # uses default pack (must be set)
mdi-kit extract --pack finance/invoice_v1 <FILE>
mdi-kit extract --pack legal/contract_v1 \
                --filters parties,effective_date \
                --json <FILE>
mdi-kit extract --stateless <FILE>                  # override any configured state

# Packs
mdi-kit packs list                                  # what's available in the registry
mdi-kit packs list --local                          # what's cached locally
mdi-kit packs show finance/invoice_v1               # print schema, prompts, rules
mdi-kit packs pull finance/invoice_v1@2.3           # fetch a specific version
mdi-kit packs push ./my-pack.yaml                   # publish (requires registry write access)

# Config
mdi-kit config init                                 # writes ~/.mdi-kit/config.toml
mdi-kit config show
mdi-kit config set provider.vertex.project my-gcp-project

# Migration / repair
mdi-kit doctor                                      # env check (pgvector, provider auth, etc.)
```

**Config resolution order** (highest wins):
1. Explicit constructor args in Python
2. Environment variables (`MDI_KIT_PROVIDER=vertex`, `MDI_KIT_VERTEX_PROJECT=...`)
3. Project-local `.mdi-kit.toml` (walked upward from CWD)
4. User config `~/.mdi-kit/config.toml`
5. Built-in defaults

---

## 5. Run modes

### 5.1 Stateless (default)

- No database
- No pattern memory across extractions
- No correction learning
- Heuristic pass always runs; LLM pass runs if a provider is configured
- Best for: high-throughput one-shot extraction, air-gapped tests, CI

### 5.2 Stateful

- Requires `PostgresStorage` (+ pgvector extension)
- Pattern memory persists across extractions in the same `project_id`
- Corrections logged and biased into future extractions (via few-shot at prompt time)
- Best for: teams that want extractions to get better over time within their own project

Cross-project isolation is enforced two ways:
1. **App-level**: every query filters by `project_id`
2. **DB-level**: RLS policy on every table (`enable_rls=True`) — even if
   app-level filtering has a bug, RLS backstops it

---

## 6. Pack registry

### 6.1 Layout

Packs live in a Git repo, one directory per pack, semver directory names
optional (latest = HEAD of main; pinned = git tag):

```
mdi-packs/
  finance/
    invoice_v1/
      pack.yaml
      schema/fields.yaml
      prompts/invoice.md
      rules/validators.yaml
      enrichment/vendor_aliases.csv
      samples/                      # optional — for CI accuracy tests
        sample-1.pdf
        sample-1.expected.yaml
  legal/
    contract_v1/
      ...
```

### 6.2 `pack.yaml` — the manifest

```yaml
name: finance/invoice_v1
version: 2.3.0
description: Standard vendor invoice extraction (US format bias).
maintainer: mdi-core@techjays.com
license: internal

schema: schema/fields.yaml
prompts:
  invoice: prompts/invoice.md
  credit_note: prompts/credit_note.md          # optional per-doc-type prompt
validators: rules/validators.yaml
enrichment:
  vendor_aliases: enrichment/vendor_aliases.csv

# Runtime hints
extraction:
  primary_route: hybrid                        # heuristic | hybrid | llm | vlm
  needs_vision: false                          # if true, forces VLM path
  timeout_seconds: 45
```

### 6.3 Publishing

- Kit reads packs by git ref: `mdi-kit packs pull finance/invoice_v1@v2.3`
- Publish = PR to `mdi-packs` repo; CI runs the accuracy test suite against
  `samples/` before merge
- Semver tag on merge; kit resolves `@2` to latest 2.x, `@2.3` to latest 2.3.x, etc.

### 6.4 Local override

For pack development without publishing:

```python
brain = Brain(pack=Pack.from_yaml("./my-pack/pack.yaml"))
```

Or via CLI:
```
mdi-kit extract --pack ./my-pack file.pdf
```

---

## 7. Repository restructure — the enabling refactor

Current layout is a monolith:

```
mdi/
  src/mdi/           ← everything (API, brain, models, packs, streamlit UI)
  frontend/          ← Next.js
  tests/
```

Target monorepo layout:

```
mdi/
  packages/
    mdi-core/                    ← pure pipeline · no HTTP · no UI
      src/mdi_core/
        brain/                   (Eyes, Hippocampus, Pattern Cortex, Hands, Conscience)
        parsers/                 (pdfplumber, docling adapters)
        gateway/                 (LLM router + provider adapters)
        heuristic/               (regex extractor)
        embeddings/              (bge-m3)
        types/                   (dataclasses shared by all packages)
      pyproject.toml

    mdi-kit/                     ← consumer library
      src/mdi_kit/
        __init__.py              (public: Brain, Pack, ExtractResult, ...ProviderConfig)
        brain.py                 (Brain wrapper over mdi-core)
        pack.py                  (Pack loader + composer)
        cli.py                   (typer-based CLI)
        storage/                 (PostgresStorage, InMemoryStorage)
        registry/                (git-backed pack registry client)
        config.py                (toml + env resolution)
      pyproject.toml
      tests/

    mdi-studio/                  ← existing FastAPI + Next.js
      src/mdi_studio/            (moves from src/mdi/api + src/mdi/ui)
      frontend/                  (moves from top-level frontend/)
      pyproject.toml

    mdi-packs/                   ← YAML packs (may become its own repo later)
      finance/
      legal/
      procurement/
      insurance/                 (existing)
      telecom/                   (existing)

  pyproject.toml                 ← workspace root (uv workspaces or hatch)
```

**Import graph rules:**
- `mdi-core` imports only third-party libs — no other `mdi-*` package
- `mdi-kit` imports from `mdi-core`
- `mdi-studio` imports from `mdi-core` (never from `mdi-kit`)
- `mdi-packs` is data, not code — no imports at all

Package boundary lint enforced via `import-linter` in CI.

---

## 8. Migration from the current platform

The existing platform stays working throughout the refactor. Rough sequence:

| Step | Action | Risk |
|---|---|---|
| M1 | Create `packages/mdi-core/` and move `src/mdi/brain/`, `src/mdi/kernel/`, `src/mdi/parsers/`, `src/mdi/models/` into it. Update all imports in `src/mdi/api/` and `src/mdi/ui/`. | Medium — mechanical but touches every file. |
| M2 | Move `src/mdi/api/` + `frontend/` into `packages/mdi-studio/`. `mdi-studio` now imports `from mdi_core.brain import ...`. Verify existing tests + Studio UI still work. | Low — pure reorganization. |
| M3 | Create `packages/mdi-kit/` with `Brain`, `Pack`, `ExtractResult`, `CLI` stubs. Wire `Brain.extract` to `mdi_core.brain.orchestrator.run_pipeline`. Ship stateless mode only. | High — first new public API. Get 1 consumer to validate before locking. |
| M4 | Add `PostgresStorage` + stateful mode. Reuse `mdi-core`'s existing SQLAlchemy models but namespace tables under `mdi_kit.<project_id>` schema. | Medium — RLS policy needs testing. |
| M5 | Add Vertex AI provider adapter (parallel with existing Gemini adapter — same underlying `google-genai` SDK, different auth path). | Low — additive. |
| M6 | Move `packs/insurance/` and `packs/telecom/` from `src/mdi/packs/` into `packages/mdi-packs/`. Author `finance/invoice_v1`, `legal/contract_v1`, `procurement/po_v1`. | Medium — new packs need accuracy testing. |
| M7 | Ship `pip install mdi-kit` internally. First consumer onboards. | Low — the work is done; this is packaging. |

Studio's existing REST API remains unchanged throughout. Studio continues
to serve its current URL. Nothing external breaks.

---

## 9. Non-goals for v1 (deferred to v2+)

- **Shared cross-project brain.** Corrections stay within a project.
- **Hosted SaaS API.** Library-first was the chosen consumption model.
- **JS/TS SDK.** Backend/data consumers first; UI SDK is a v2 conversation.
- **Cross-org pack marketplace.** Org-private only.
- **Streaming extraction.** Batch-only; return the whole `ExtractResult` at once.
- **Studio ↔ Kit live sync.** Packs flow through the git registry, not a live protocol.
- **Handwriting-specialized OCR, tenant-scoped fine-tuning, M365 push subscription.** In `documents/platform-overview.html` Part C's hold-it bucket.

---

## 10. Success criteria (from Part D §8)

| Criterion | Measurable target |
|---|---|
| Consumer onboarding cost | ≤ 10 lines of Python from `pip install` to first structured extraction |
| First-doc latency (stateless, heuristic) | < 500 ms per file |
| First-doc latency (stateless, Full mode via Vertex) | < 45 s per file |
| Reference packs shipped | 3 packs (invoice, contract, PO), each with ≥ 5 sample documents and ≥ 85% field-level accuracy |
| Docs completeness | 5 pages minimum — getting-started, filter composition, custom pack authoring, provider config, troubleshooting |
| First real consumer | ≥ 1 internal team using it against their own document corpus without hand-holding |

---

## 11. Open questions

Questions we're deliberately leaving open for the build phase — they don't
block starting v1 but need answers before shipping:

1. **`ExtractResult` serialization format.** JSON is baseline. Do we ship
   Parquet/Arrow adapters in v1 for teams pushing extractions into
   BigQuery/data lakes? *(Lean: JSON only in v1; adapters as opt-in extras.)*
2. **Pack authoring in Studio vs YAML-first.** Studio has a UI for pack
   authoring. Do we invest in that UI in v1, or ship YAML-only and treat
   the UI as a v2 optimization? *(Lean: YAML-only in v1.)*
3. **Registry authentication.** Git access controls handle it for private
   packs, but do we need per-pack ACLs *within* the registry? *(Lean: no
   in v1 — the whole registry is org-private, use git branch protections.)*
4. **Kit telemetry.** Should the kit phone home usage metrics
   (extractions/day, packs used, error rates) to a central endpoint for
   MDI core team observability? *(Needs privacy sign-off — leaning:
   opt-in only, off by default.)*
5. **Cost caps in stateful mode.** When a consumer configures Vertex,
   should the kit enforce a monthly USD cap per `project_id`? *(Lean: yes
   — default $500/mo, configurable; raises `CostCapExceeded` clearly.)*

---

## 12. Related docs

- [`documents/platform-overview.html`](documents/platform-overview.html) — customer/stakeholder-facing overview (Part D covers this initiative at a higher altitude)
- [`documents/platform-overview.md`](documents/platform-overview.md) — markdown source of the above
- `src/mdi/brain/` — existing pipeline that `mdi-core` will absorb
- `src/mdi/packs/insurance/` and `telecom/` — existing packs, become the seed for `mdi-packs/`
