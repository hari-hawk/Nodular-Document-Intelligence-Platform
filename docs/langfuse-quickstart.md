# Langfuse — self-hosted trace UI for MDI

**What it is**: Free, open-source observability for every LLM call MDI makes. Per-call prompt + response, latency, token counts, cost, fallback chain index, and any metadata the gateway attaches (organ, tenant_id, request_id).

**What it is not (yet)**: A drop-in replacement for `structlog`. Both run in parallel — Langfuse for *traces* (per-call UI), structlog for *events* (the things that aren't a single LLM call: pack discovery, pattern hits, anomaly counts).

---

## 30-second setup

```bash
# 1. Start the stack — postgres now bootstraps a `langfuse` DB on first boot,
#    and a langfuse service exposes the UI on :3100.
docker-compose up -d

# 2. Open the UI, create a project, copy the keys
open http://localhost:3100
#   → Sign up (any email/password — it's local)
#   → Create a project
#   → Settings → API Keys → "Create new API keys"
#   → Copy "Public Key" and "Secret Key"

# 3. Paste keys into .env
cat >> .env << 'EOF'
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=http://localhost:3100
EOF

# 4. Restart the API so the new keys load
# (no migration needed; observability.py picks up the keys via settings)
```

That's it. Run any extraction (live eval, /process endpoint, smoke test with `--run-live`) and traces appear in the UI within a few seconds.

---

## What you see in the UI

Each LLM call from MDI's gateway is wrapped as a Langfuse trace with:

| Field | Where it comes from |
|---|---|
| `name` | `llm:<organ>` — e.g. `llm:eyes`, `llm:hands`, `llm:pattern_cortex` |
| `metadata.request_id` | A UUID per gateway call so you can join with structlog events |
| `metadata.provider` | `gemini` or `anthropic` (or `vertex` once you flip the backend env) |
| `metadata.model` | The actual model name (`gemini-2.5-flash`, `claude-opus-4-1`, etc.) |
| `metadata.fallback_index` | 0 for primary, 1 for first fallback. Filter `>=1` to find every time the chain fell through. |
| `metadata.tenant_id` | RLS-scoped. Useful for "what did this customer cost us this week?" |
| `usage.input_tokens` / `usage.output_tokens` | Surface for cost forensics. |

The fallback-index column is the single most useful signal — it answers "how often is Gemini failing such that Claude has to pick up?" without grepping structlog files.

---

## Without keys, nothing changes

`mdi/kernel/observability.py` has a `_NoopLangfuse` shim that returns trace objects with no-op `end()` calls. When `LANGFUSE_PUBLIC_KEY` is empty (which is the default), every `gateway.generate()` call goes through the no-op path — zero network, zero overhead. So:

- **Local dev without Langfuse**: same as today, nothing to do.
- **Local dev with Langfuse**: docker-compose up + paste keys + restart API.
- **CI**: don't set the keys → traces stay no-op → no CI-time dependency on Langfuse.
- **Production**: set keys via secret manager; point `LANGFUSE_HOST` at your prod Langfuse URL (could be the same self-hosted instance behind a VPN, or LangSmith later).

---

## Common queries once data is flowing

| Question | Query in Langfuse UI |
|---|---|
| All fallbacks today | `metadata.fallback_index >= 1` |
| Hands extractions over $0.05 | `name = "llm:hands"` and sort by total cost |
| What did tenant X cost this week? | `metadata.tenant_id = "<uuid>"` + date filter |
| Slowest narrator calls | `name = "llm:narrator"` sort by latency DESC |
| Which docs hit Claude on extraction | filter `name = "llm:hands"` AND `metadata.provider = "anthropic"` |

---

## Deferred — LangSmith

Per the Wave 1.5 confirmation (Hari, 2026-06-04): Langfuse self-hosted for now, LangSmith later. When that day comes the migration is:

1. Sign up at smith.langchain.com, get keys.
2. The codebase already has the `langfuse` SDK contract; switching to LangSmith means rewriting `_NoopLangfuse` → a LangSmith client of the same shape.
3. Or: use Langfuse Cloud (paid) for the same code surface with no migration.

This decision is reversible. The point of having the abstraction in `observability.py` is that the application code never directly imports Langfuse — `get_langfuse()` returns whatever observability backend is configured.
