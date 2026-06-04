"""MDI analyst console — professional Streamlit UI.

Layout:
  Sidebar       — tenant picker, provider chain summary, cost-to-date
  Dashboard tab — KPIs, recent batches, routing diagram
  Upload tab    — drag-drop multi-file, run pipeline, real-time stage progress
  Results tab   — interactive data grid + Excel/CSV export
  Knowledge tab — pyvis-rendered graph of entities + relationships
  Patterns tab  — pattern memory state (vendor × industry × doc_type)
  Chat tab      — graph-routed + LLM hybrid Q&A
  Settings tab  — provider routing policy, cost caps, RLS status

Local mode: pipeline is invoked **in-process** (skip the FastAPI hop) so
the user only has to start ONE process to see everything working.
"""
from __future__ import annotations

import asyncio
import io
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# Pre-flight: load .env, ensure src on path (Streamlit runs from any cwd).
# ---------------------------------------------------------------------------
_THIS = Path(__file__).resolve()
_SRC = _THIS.parents[2]
_ROOT = _SRC.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

env_path = _ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from mdi.brain.hippocampus import Hippocampus
from mdi.kernel import provider_router
from mdi.kernel.auth import reset_engine, tenant_session
from mdi.kernel.llm_gateway import reset_gateway
from mdi.kernel.providers.base import reset_providers
from mdi.kernel.settings import get_settings
from mdi.orchestrator.pipeline import run_batch_async

# ---------------------------------------------------------------------------
# Page config + custom CSS
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="MDI · Modular Data Intelligence",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Stitch-style polish: tighter spacing, modern card look, gradient accent.
st.markdown(
    """
    <style>
    /* Headline accent */
    .mdi-hero { font-size: 1.8rem; font-weight: 700;
                background: linear-gradient(90deg, #6366F1, #EC4899);
                -webkit-background-clip: text; -webkit-text-fill-color: transparent;
                margin-bottom: 0.25rem; }
    .mdi-sub  { color: #9CA3AF; font-size: 0.9rem; margin-bottom: 1.5rem; }

    /* Card */
    .mdi-card { background: #141B2D; border: 1px solid #1F2A44;
                border-radius: 12px; padding: 1rem 1.25rem; }
    .mdi-card h3 { margin: 0 0 0.25rem 0; font-size: 1rem; color: #E5E7EB; }
    .mdi-card .v { font-size: 1.5rem; font-weight: 700; color: #F9FAFB; }
    .mdi-card .s { font-size: 0.75rem; color: #9CA3AF; }

    /* Badges */
    .mdi-badge { display: inline-block; padding: 2px 10px; border-radius: 999px;
                 font-size: 0.7rem; font-weight: 600; margin-right: 6px; }
    .b-ok       { background: rgba(34,197,94,0.15); color: #4ADE80; }
    .b-warn     { background: rgba(234,179,8,0.15); color: #FACC15; }
    .b-info     { background: rgba(99,102,241,0.15); color: #818CF8; }
    .b-err      { background: rgba(239,68,68,0.15); color: #F87171; }

    /* Tabs — tighter */
    .stTabs [data-baseweb="tab-list"] { gap: 4px; }
    .stTabs [data-baseweb="tab"] { padding: 8px 18px; border-radius: 8px; }
    .stTabs [aria-selected="true"] { background-color: #1F2A44; color: #E5E7EB; }

    /* Sidebar */
    [data-testid="stSidebar"] { background: #0E1424; border-right: 1px solid #1F2A44; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
DEFAULT_TENANT_A = "11111111-1111-1111-1111-111111111111"
DEFAULT_TENANT_B = "22222222-2222-2222-2222-222222222222"


def _kpi(col, label: str, value: str, sub: str = "") -> None:
    col.markdown(
        f"""<div class="mdi-card"><h3>{label}</h3>
        <div class="v">{value}</div>
        <div class="s">{sub}</div></div>""",
        unsafe_allow_html=True,
    )


def _badge(label: str, kind: str = "info") -> str:
    return f'<span class="mdi-badge b-{kind}">{label}</span>'


# ---------------------------------------------------------------------------
# Service health probes — cached 10s so they don't add latency to every render.
# Streamlit's cache invalidates by (function, args, ttl) so each probe runs
# at most once per 10s window per process.
# ---------------------------------------------------------------------------
@st.cache_data(ttl=10, show_spinner=False)
def _probe_api_health(api_url: str = "http://127.0.0.1:8080") -> dict[str, Any]:
    """Probe the FastAPI /health endpoint. Returns {up, ms, error}."""
    import time

    import httpx
    t0 = time.monotonic()
    try:
        r = httpx.get(f"{api_url}/health", timeout=1.5)
        elapsed = int((time.monotonic() - t0) * 1000)
        return {"up": r.status_code == 200, "ms": elapsed,
                "error": None if r.status_code == 200 else f"HTTP {r.status_code}"}
    except Exception as e:
        elapsed = int((time.monotonic() - t0) * 1000)
        return {"up": False, "ms": elapsed,
                "error": f"{type(e).__name__}: {str(e)[:80]}"}


@st.cache_data(ttl=10, show_spinner=False)
def _probe_db_health() -> dict[str, Any]:
    """Probe Postgres with a 1s SELECT 1. Bypasses RLS via the app role."""
    import time
    t0 = time.monotonic()
    try:
        import psycopg
        s = get_settings()
        # Strip the SQLAlchemy driver prefix for a direct psycopg connection.
        dsn = s.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        with psycopg.connect(dsn, connect_timeout=2) as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        elapsed = int((time.monotonic() - t0) * 1000)
        return {"up": True, "ms": elapsed, "error": None}
    except Exception as e:
        elapsed = int((time.monotonic() - t0) * 1000)
        return {"up": False, "ms": elapsed,
                "error": f"{type(e).__name__}: {str(e)[:80]}"}


def _run_pipeline_sync(tenant_id: str, payloads: list[dict[str, Any]]) -> dict[str, Any]:
    """Run the async pipeline from the Streamlit (sync) context."""
    reset_gateway()
    reset_providers()
    reset_engine()
    hippo = Hippocampus(use_real_embeddings=False)
    return asyncio.run(
        run_batch_async(
            tenant_id=tenant_id,
            payloads=payloads,
            hippocampus=hippo,
            persist=True,
        )
    )


def _normalize_field_name(name: str) -> str:
    """Delegate to the canonical module (single source of truth).

    With orchestrator-level normalisation in place, extractions persisted
    after this turn already use canonical names. This helper still runs
    for backwards compatibility with rows persisted before the change.
    """
    from mdi.brain._canonical_fields import canonical_name
    return canonical_name(name)


def _flatten_extraction(filename: str, doc_id: str, cluster: dict, ex: dict) -> dict[str, Any]:
    """One row per document for the data grid."""
    row: dict[str, Any] = {
        "filename": filename,
        "industry": cluster.get("industry"),
        "vendor": cluster.get("vendor"),
        "doc_type": cluster.get("doc_type"),
        "confidence": round(float(cluster.get("confidence") or 0), 2),
        "document_id": doc_id[:8],
    }
    for raw_name, field in (ex.get("fields") or {}).items():
        canonical = _normalize_field_name(raw_name)
        # If multiple raw names map to the same canonical, the first one wins.
        if canonical not in row:
            row[canonical] = field.get("value")
    return row


# ---------------------------------------------------------------------------
# Sidebar — tenant picker + status
# ---------------------------------------------------------------------------
def render_sidebar() -> str:
    s = get_settings()
    st.sidebar.markdown('<div class="mdi-hero">🧠 MDI</div>', unsafe_allow_html=True)
    st.sidebar.caption("Modular Data Intelligence · Analyst Console")

    # Service health — top of the sidebar so it's visible from every tab.
    api = _probe_api_health()
    db = _probe_db_health()
    api_label = f"API {api['ms']}ms" if api["up"] else "API ×"
    db_label = f"DB {db['ms']}ms" if db["up"] else "DB ×"
    api_kind = "ok" if api["up"] else "err"
    db_kind = "ok" if db["up"] else "err"
    st.sidebar.markdown(
        _badge(api_label, api_kind) + _badge(db_label, db_kind),
        unsafe_allow_html=True,
    )
    if not api["up"]:
        st.sidebar.caption(f"API: {api['error']}")
        st.sidebar.caption("Start it: `mdi-api` (or `uvicorn mdi.api.main:app --port 8080`)")
    if not db["up"]:
        st.sidebar.caption(f"DB: {db['error']}")

    st.sidebar.divider()
    tenant_choice = st.sidebar.selectbox(
        "Active tenant",
        options=[
            ("Tenant A (default)", DEFAULT_TENANT_A),
            ("Tenant B", DEFAULT_TENANT_B),
        ],
        format_func=lambda x: x[0],
    )
    tenant_id = tenant_choice[1]
    st.sidebar.code(tenant_id, language="text")

    # Provider chain summary
    st.sidebar.divider()
    st.sidebar.markdown("**Routing policy**")
    try:
        chains = provider_router.describe()
        for tier, chain in chains.items():
            primary, fb = chain[0], chain[1] if len(chain) > 1 else None
            line = f"`{tier}` → {primary[0]}/{primary[1].split('-')[1] if '-' in primary[1] else primary[1]}"
            if fb:
                line += f" → fb {fb[0]}"
            st.sidebar.caption(line)
    except Exception as e:
        st.sidebar.warning(f"Router error: {e}")

    # Provider configuration
    st.sidebar.divider()
    st.sidebar.markdown("**Providers**")
    gem_ok = bool(s.google_api_key)
    ant_ok = bool(s.anthropic_api_key)
    st.sidebar.markdown(
        f"{_badge('Gemini', 'ok' if gem_ok else 'err')} "
        f"{_badge('Anthropic', 'ok' if ant_ok else 'warn')}",
        unsafe_allow_html=True,
    )

    # Embedder mode + load state — visible from every tab.
    st.sidebar.divider()
    st.sidebar.markdown("**Embedder**")
    from mdi.brain.hippocampus import embedder_status
    es = embedder_status()
    if es["mode"] == "stub":
        st.sidebar.markdown(_badge("stub (identical-only)", "warn"),
                            unsafe_allow_html=True)
    elif es["loaded"]:
        st.sidebar.markdown(_badge(f"bge-m3 · {es['device']}", "ok"),
                            unsafe_allow_html=True)
    elif es["loading"]:
        st.sidebar.markdown(_badge("bge-m3 loading…", "warn"),
                            unsafe_allow_html=True)
    else:
        st.sidebar.markdown(_badge("bge-m3 · cold", "info"),
                            unsafe_allow_html=True)
        st.sidebar.caption("Loads on first use (~30s)")

    # Cost
    st.sidebar.divider()
    st.sidebar.markdown("**Cost ceiling**")
    st.sidebar.caption(f"Daily cap: ${s.daily_spend_cap_usd:.2f}")

    return tenant_id


# ---------------------------------------------------------------------------
# Tab: Dashboard
# ---------------------------------------------------------------------------
def tab_dashboard(tenant_id: str) -> None:
    st.markdown('<div class="mdi-hero">Dashboard</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="mdi-sub">Real-time view of the brain — what\'s been processed, what it learned, what it spent.</div>',
        unsafe_allow_html=True,
    )

    # KPIs across the top
    counts = _fetch_dashboard_counts(tenant_id)
    c1, c2, c3, c4 = st.columns(4)
    _kpi(c1, "Documents", f"{counts['documents']}", "all-time, this tenant")
    _kpi(c2, "Patterns learned", f"{counts['patterns']}", "by (industry, vendor, doc_type)")
    _kpi(c3, "KG entities", f"{counts['kg_nodes']}", f"{counts['kg_edges']} edges")
    _kpi(c4, "Total spend", f"${counts['cost_usd']:.4f}", "across all batches")

    st.markdown("")

    # The pipeline diagram
    st.markdown("### Pipeline — 19 stages")
    st.markdown(
        """
        <div class="mdi-card">
        <strong>Phase 1 · Per-document</strong><br/>
        <code>1 ingest → 2 classify (Eyes) → 3 memory check → 4 schema discovery (Pattern Cortex)
         → 5 rule invention (Conscience) → 6 correction lookup → 7 extract (Hands) → 8 validate → 9 memory write</code><br/><br/>
        <strong>Phase 2 · Batch analysis</strong><br/>
        <code>10 insights (Insight Cortex) → 11 reflection (Inner Voice) → 12 group discovery → 13 coverage</code><br/><br/>
        <strong>Phase 3 · Report</strong><br/>
        <code>14 account briefings → 15 narrator → 16 BatchReport</code><br/><br/>
        <strong>Phase 4 · Knowledge graph</strong><br/>
        <code>17 graph build → 18 graph insights → 19 cross-doc validation</code>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Recent batches
    st.markdown("### Recent batches")
    batches = _fetch_batches(tenant_id, limit=10)
    if batches:
        st.dataframe(
            pd.DataFrame(batches),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No batches yet. Go to the **Upload** tab to process some documents.")


# ---------------------------------------------------------------------------
# Tab: Upload
# ---------------------------------------------------------------------------
def tab_upload(tenant_id: str) -> None:
    st.markdown('<div class="mdi-hero">Upload</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="mdi-sub">Drag documents in. The brain classifies, extracts, validates, and writes to the KG.</div>',
        unsafe_allow_html=True,
    )

    files = st.file_uploader(
        "Drop PDF / DOCX / XLSX / CSV / TXT / image files",
        accept_multiple_files=True,
        type=["pdf", "docx", "xlsx", "xls", "csv", "tsv", "txt", "png", "jpg", "jpeg", "tiff", "bmp", "webp"],
    )

    col_run, _ = st.columns([1, 5])
    run = col_run.button("▶ Run pipeline", type="primary", disabled=not files, use_container_width=True)

    if run and files:
        payloads = [{"filename": f.name, "content": f.getvalue()} for f in files]
        progress_bar = st.progress(0, text="Starting pipeline…")


        with st.spinner("Processing batch through 19 stages…"):
            t0 = time.monotonic()
            report = _run_pipeline_sync(tenant_id, payloads)
            elapsed = time.monotonic() - t0
        progress_bar.progress(100, text="Done")

        st.success(
            f"✓ Processed {len(files)} document(s) in {elapsed:.1f}s · "
            f"Cost ${report['total_cost_usd']:.5f}"
        )

        # Live progress trail
        with st.expander("📊 Stage-by-stage trail", expanded=True):
            for line in report.get("progress", []):
                st.code(line, language="text")

        # Persist last report in session for the Results tab
        st.session_state["last_report"] = report

        # Quick preview
        if report.get("extractions"):
            st.markdown("### Quick extraction preview")
            rows = []
            for did, ex in report["extractions"].items():
                fn = next((d["filename"] for d in report["documents"] if d["document_id"] == did), "?")
                cluster = report["clusters"].get(did, {})
                rows.append(_flatten_extraction(fn, did, cluster, ex))
            preview_df = pd.DataFrame(rows)
            st.dataframe(preview_df, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Tab: Results — data grid + Excel/CSV export
# ---------------------------------------------------------------------------
def tab_results(tenant_id: str) -> None:
    st.markdown('<div class="mdi-hero">Results</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="mdi-sub">Every extraction this tenant has accumulated, normalized into one data grid. Export Excel or CSV.</div>',
        unsafe_allow_html=True,
    )

    rows = _fetch_all_extractions(tenant_id)
    if not rows:
        st.info("No extractions yet for this tenant.")
        return

    df = pd.DataFrame(rows)

    # Filters bar
    f1, f2, f3 = st.columns(3)
    industries = sorted({r.get("industry") for r in rows if r.get("industry")})
    doc_types = sorted({r.get("doc_type") for r in rows if r.get("doc_type")})
    vendors = sorted({r.get("vendor") for r in rows if r.get("vendor")})
    sel_industry = f1.multiselect("Industry", industries, default=industries)
    sel_type = f2.multiselect("Doc type", doc_types, default=doc_types)
    sel_vendor = f3.multiselect("Vendor", vendors, default=vendors)

    mask = df["industry"].isin(sel_industry) & df["doc_type"].isin(sel_type) & df["vendor"].isin(sel_vendor)
    df_view = df[mask]

    st.dataframe(
        df_view,
        use_container_width=True,
        hide_index=True,
        column_config={
            "confidence": st.column_config.ProgressColumn(
                "Confidence", format="%.2f", min_value=0.0, max_value=1.0,
            ),
            "document_date": st.column_config.DateColumn("Doc Date"),
            "due_date": st.column_config.DateColumn("Due Date"),
        },
    )

    # Export
    st.markdown("### Export")
    st.caption("Same data, five formats. Pick whichever your downstream consumer prefers.")
    col_xlsx, col_csv, col_pdf, col_eml, col_json = st.columns(5)

    # Excel
    xlsx_buf = io.BytesIO()
    with pd.ExcelWriter(xlsx_buf, engine="openpyxl") as writer:
        df_view.to_excel(writer, index=False, sheet_name="Extractions")
    col_xlsx.download_button(
        "⬇ Excel (.xlsx)",
        data=xlsx_buf.getvalue(),
        file_name=f"mdi_export_{tenant_id[:8]}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
    # CSV
    col_csv.download_button(
        "⬇ CSV",
        data=df_view.to_csv(index=False).encode("utf-8"),
        file_name=f"mdi_export_{tenant_id[:8]}.csv",
        mime="text/csv",
        use_container_width=True,
    )

    # PDF / Email / JSON — these need the last batch report (richer than the flat grid).
    report = st.session_state.get("last_report")
    if report:
        from mdi.eval.exports import to_email_html, to_eml_bytes, to_json_bytes, to_pdf_bytes
        col_pdf.download_button(
            "⬇ PDF",
            data=to_pdf_bytes(report, mode="detailed"),
            file_name=f"mdi_report_{tenant_id[:8]}.pdf",
            mime="application/pdf",
            use_container_width=True,
        )
        col_eml.download_button(
            "⬇ Email (.eml)",
            data=to_eml_bytes(report),
            file_name=f"mdi_report_{tenant_id[:8]}.eml",
            mime="message/rfc822",
            use_container_width=True,
        )
        col_json.download_button(
            "⬇ JSON",
            data=to_json_bytes(report),
            file_name=f"mdi_report_{tenant_id[:8]}.json",
            mime="application/json",
            use_container_width=True,
        )
        with st.expander("📧 Preview Email HTML"):
            st.components.v1.html(to_email_html(report), height=520, scrolling=True)
    else:
        col_pdf.caption("Run a batch first")
        col_eml.caption("Run a batch first")
        col_json.caption("Run a batch first")


# ---------------------------------------------------------------------------
# Tab: Knowledge Graph
# ---------------------------------------------------------------------------
def tab_graph(tenant_id: str) -> None:
    st.markdown('<div class="mdi-hero">Knowledge Graph</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="mdi-sub">Entities and relationships discovered across documents. Drag to explore.</div>',
        unsafe_allow_html=True,
    )
    nodes, edges = _fetch_graph(tenant_id)
    if not nodes:
        st.info("No graph data yet — process some documents first.")
        return

    c1, c2, c3 = st.columns(3)
    _kpi(c1, "Nodes", f"{len(nodes)}", "Vendor · Customer · Account · Document …")
    _kpi(c2, "Edges", f"{len(edges)}", "BILLED_BY · BELONGS_TO · INVOICE_FOR …")
    _kpi(c3, "Node types", f"{len({n['node_type'] for n in nodes})}", "distinct types")

    st.markdown("")

    # Build pyvis viz
    from pyvis.network import Network

    net = Network(
        height="600px", width="100%", bgcolor="#0B1020", font_color="#E5E7EB",
        directed=True, notebook=False,
    )
    net.barnes_hut(gravity=-9000, spring_length=180, central_gravity=0.18)
    type_colour = {
        "Vendor":   "#F87171", "Customer":  "#60A5FA",
        "Account":  "#FBBF24", "Contract":  "#A78BFA",
        "Document": "#34D399", "Patient":   "#F472B6",
        "Provider": "#22D3EE", "PurchaseOrder": "#FB923C",
        "Phone":    "#94A3B8", "Address":   "#94A3B8",
        "Employee": "#94A3B8", "Generic":   "#6B7280",
    }
    for n in nodes:
        net.add_node(
            str(n["id"]),
            label=f"{n['canonical_key'][:24]}",
            title=f"{n['node_type']}: {n['canonical_key']}",
            color=type_colour.get(n["node_type"], "#6B7280"),
            size=18 if n["node_type"] in {"Vendor", "Customer", "Account"} else 12,
        )
    for e in edges:
        net.add_edge(
            str(e["src_id"]),
            str(e["dst_id"]),
            label=e["edge_type"],
            color="#475569",
            arrows="to",
        )

    html_path = Path(tempfile.gettempdir()) / f"mdi_kg_{tenant_id}.html"
    net.save_graph(str(html_path))
    st.components.v1.html(html_path.read_text(), height=620, scrolling=False)


# ---------------------------------------------------------------------------
# Tab: Patterns — memory state
# ---------------------------------------------------------------------------
def tab_patterns(tenant_id: str) -> None:
    st.markdown('<div class="mdi-hero">Pattern Memory</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="mdi-sub">What the brain has memorized. Patterns short-circuit Pattern Cortex on similar docs (the self-improvement loop).</div>',
        unsafe_allow_html=True,
    )
    patterns = _fetch_patterns(tenant_id)
    if not patterns:
        st.info("No patterns yet.")
        return
    df = pd.DataFrame(patterns)
    st.dataframe(df, use_container_width=True, hide_index=True)

    # If this tenant has a pack assigned, render its contract below.
    rows = _run_query(tenant_id,
                      "SELECT pack_slug FROM tenants WHERE id = :tid",
                      tid=tenant_id)
    pack_slug = (rows[0].get("pack_slug") if rows else None)
    if pack_slug:
        st.markdown("### Active pack contract")
        st.caption(
            f"This tenant is assigned `{pack_slug}` — new uploads use its schema "
            "and validators. Open-vocabulary discovery still runs but the pack "
            "fields are authoritative."
        )
        manifest = _admin_get_pack(get_settings().admin_api_key, pack_slug)
        if manifest:
            _render_pack_viewer(manifest)
    else:
        st.caption("This tenant is on open-vocabulary mode — no pack assigned. "
                   "Patterns reflect what the brain discovered from samples.")


# ---------------------------------------------------------------------------
# Tab: EvalLayers — per-stage quality gates
# ---------------------------------------------------------------------------
def tab_evals(tenant_id: str) -> None:
    st.markdown('<div class="mdi-hero">EvalLayers</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="mdi-sub">Per-stage quality gates. Each organ runs an EvalLayer after its work; results aggregate here so silent degradation surfaces fast.</div>',
        unsafe_allow_html=True,
    )

    report = st.session_state.get("last_report")
    if not report:
        st.info("No batch in this session yet. Upload some documents first.")
        return

    evals = report.get("stage_evals") or []
    if not evals:
        st.warning("This batch has no eval results. Re-run after the eval layer was wired in.")
        return

    pass_count = sum(1 for e in evals if e.get("passed"))
    fail_count = len(evals) - pass_count
    c1, c2, c3 = st.columns(3)
    _kpi(c1, "Eval results", f"{len(evals)}", "across all stages")
    _kpi(c2, "Passing", f"{pass_count}", f"of {len(evals)}")
    _kpi(c3, "Failing", f"{fail_count}", "needs review" if fail_count else "all good")

    st.markdown("")

    # Summary table
    rows = []
    for e in evals:
        rows.append({
            "Stage": e.get("stage_name"),
            "Organ": e.get("organ"),
            "Passed": "✅" if e.get("passed") else "❌",
            "Score": round(float(e.get("score") or 0), 3),
            "Severity": e.get("severity"),
            "Checks": f"{sum(1 for c in e.get('checks') or [] if c.get('passed'))}/{len(e.get('checks') or [])}",
            "Document": (str(e.get("document_id") or "")[:8] or "—"),
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True,
                 column_config={
                     "Score": st.column_config.ProgressColumn(
                         "Score", format="%.2f", min_value=0.0, max_value=1.0,
                     ),
                 })

    # Per-tenant thresholds — read from tenants.config["eval_thresholds"]
    import asyncio as _asyncio

    from sqlalchemy import text as _t
    async def _load_thresholds():
        async with tenant_session(tenant_id) as db:
            row = (await db.execute(_t("SELECT config FROM tenants WHERE id = :tid"),
                                    {"tid": tenant_id})).first()
            return (row.config or {}).get("eval_thresholds", {}) if row else {}
    try:
        active_thresholds = _asyncio.run(_load_thresholds())
    except Exception:
        active_thresholds = {}

    defaults = {
        "classify": 0.6, "schema_discovery": 0.6, "extract": 0.6,
        "validate": 0.7, "insights": 0.5, "graph": 0.5,
    }
    st.markdown("### Active pass thresholds (per-tenant)")
    thr_rows = []
    for k, default_v in defaults.items():
        active = active_thresholds.get(k, default_v)
        overridden = k in active_thresholds
        thr_rows.append({
            "Stage": k,
            "Default": default_v,
            "Active": active,
            "Override?": "✓" if overridden else "—",
        })
    st.dataframe(pd.DataFrame(thr_rows), use_container_width=True, hide_index=True)
    st.caption(
        "To override: `UPDATE tenants SET config = jsonb_set(config, "
        "'{eval_thresholds,extract}', '0.8') WHERE id = ...;`"
    )

    # Drill-down
    st.markdown("### Stage drill-down")
    for e in evals:
        label = f"{e.get('stage_name')} · {e.get('organ')} — score {e.get('score'):.2f}"
        icon = "✅" if e.get("passed") else "❌"
        with st.expander(f"{icon}  {label}"):
            for c in e.get("checks") or []:
                ck = "✓" if c.get("passed") else "✗"
                st.markdown(f"- {ck} **{c.get('name')}** — {c.get('detail')}")
            if e.get("attributes"):
                st.caption("Attributes")
                st.json(e["attributes"])


# ---------------------------------------------------------------------------
# Tab: Admin — tenant onboarding + API key issuance
# ---------------------------------------------------------------------------
def tab_admin() -> None:
    st.markdown('<div class="mdi-hero">Admin · Tenant Onboarding</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="mdi-sub">Create tenants, assign packs, and issue API keys without SQL. '
        'Admin actions require the <code>X-Admin-Key</code> header — value is read from '
        '<code>ADMIN_API_KEY</code> in your <code>.env</code> (default: <code>local-dev-admin-key</code>).</div>',
        unsafe_allow_html=True,
    )

    admin_key = st.text_input(
        "Admin key", value=get_settings().admin_api_key,
        type="password",
        help="Sent as the X-Admin-Key header on every admin request.",
    )

    available_packs = _admin_list_packs(admin_key)
    pack_options = ["(open-vocabulary)", *available_packs]

    # --- List tenants ---
    st.markdown("### Tenants")
    tenants = _admin_list_tenants(admin_key)
    if tenants is not None:
        if tenants:
            df = pd.DataFrame(tenants)
            df = df[["id", "slug", "display_name", "monthly_cost_cap_usd", "pack_slug", "created_at"]]
            st.dataframe(df, use_container_width=True, hide_index=True,
                         column_config={"id": st.column_config.TextColumn("Tenant ID", width="medium")})

            # Inline pack-assignment editor
            st.markdown("#### Edit pack assignment")
            st.caption(
                "Pack assignment is forward-only: existing extractions stay as-is, "
                "new uploads use the new pack's schema and validators."
            )
            edit_target = st.selectbox(
                "Tenant", tenants,
                format_func=lambda t: f"{t['slug']} · current pack: "
                                       f"{t.get('pack_slug') or '(open-vocabulary)'}",
                key="admin_pack_edit_target",
            )
            current = edit_target.get("pack_slug") or "(open-vocabulary)"
            new_pack = st.selectbox(
                "New pack", pack_options,
                index=pack_options.index(current) if current in pack_options else 0,
                key="admin_pack_edit_new",
            )
            if st.button("Save pack assignment", type="secondary"):
                pack_to_send = "" if new_pack == "(open-vocabulary)" else new_pack
                result = _admin_update_tenant(
                    admin_key, edit_target["id"], pack_slug=pack_to_send,
                )
                if result:
                    st.success(
                        f"✓ {result['slug']} now uses "
                        f"{result.get('pack_slug') or '(open-vocabulary)'}"
                    )
                    st.rerun()

            # --- Inspect a pack before committing to it ---
            if available_packs:
                st.markdown("#### Inspect a pack")
                st.caption("See the full contract before assigning — fields, "
                           "doc types, prompts, validators, merge rules.")
                inspect_target = st.selectbox(
                    "Pack to inspect", available_packs,
                    key="admin_pack_inspect",
                )
                manifest = _admin_get_pack(admin_key, inspect_target)
                if manifest:
                    _render_pack_viewer(manifest)
        else:
            st.info("No tenants yet.")

    # --- Create new tenant ---
    st.markdown("### Create tenant")
    with st.form("admin_create_tenant"):
        c1, c2, c3 = st.columns(3)
        slug = c1.text_input("Slug", placeholder="acme-corp",
                              help="URL-safe handle, 2-64 chars")
        name = c2.text_input("Display name", placeholder="Acme Corporation")
        cap = c3.number_input("Monthly cost cap (USD)", min_value=0.0,
                                value=200.0, step=10.0)
        pack_choice = st.selectbox(
            "Pack", pack_options,
            help="Open-vocabulary = brain discovers schemas from samples. "
                 "Pack = contractual schema for a vertical.",
        )
        submitted = st.form_submit_button("Create tenant + issue first key", type="primary")

    if submitted:
        if not slug or not name:
            st.error("Slug and display name are required.")
        else:
            pack_to_send = None if pack_choice == "(open-vocabulary)" else pack_choice
            result = _admin_create_tenant(
                admin_key, slug=slug, name=name, cap=float(cap),
                pack_slug=pack_to_send,
            )
            if result:
                st.success(f"✓ Tenant created: {result['tenant_id']}")
                st.warning("⚠ The API key below is shown ONCE. Copy it now.")
                st.code(result["api_key"], language="text")
                st.session_state["last_issued_key"] = result["api_key"]

    # --- Issue another key for an existing tenant ---
    st.markdown("### Rotate / issue API key for existing tenant")
    if tenants:
        target = st.selectbox(
            "Target tenant",
            options=[(t["id"], f"{t['slug']} ({t['display_name']})") for t in tenants],
            format_func=lambda t: t[1],
            key="admin_rotate_target",
        )
        label = st.text_input("Key label", value="rotation",
                              help="Free-text label persisted in api_keys.label")
        if st.button("Issue new key", type="secondary"):
            result = _admin_issue_key(admin_key, tenant_id=target[0], label=label)
            if result:
                st.success("✓ New key issued.")
                st.warning("⚠ Shown ONCE. Copy it now.")
                st.code(result["api_key"], language="text")


# ---------------------------------------------------------------------------
# Tab: Audit Log — who saw what, who corrected what, when
# ---------------------------------------------------------------------------
def tab_audit(tenant_id: str) -> None:
    st.markdown('<div class="mdi-hero">Audit Log</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="mdi-sub">Every tenant-scoped state change is recorded here. Filter, drill in, export. '
        'Review-tier entity merges that need analyst confirmation are surfaced at the top.</div>',
        unsafe_allow_html=True,
    )

    rows = _fetch_audit(tenant_id)
    if not rows:
        st.info("No audit events yet for this tenant. Process a batch in the Upload tab.")
        return

    df = pd.DataFrame(rows)
    actions = sorted(df["action"].dropna().unique().tolist())
    actors = sorted(df["actor"].dropna().unique().tolist())

    # ----- KPIs + pending-review counter -----
    review_tier_items: list[tuple[str, str]] = []  # (created_at, note)
    for r in rows:
        payload = r.get("payload") or {}
        for m in (payload.get("merges") or []):
            if "review-tier" in m:
                review_tier_items.append((r.get("created_at", ""), m))

    c1, c2, c3, c4 = st.columns(4)
    _kpi(c1, "Events", str(len(df)), "this tenant, last 500")
    _kpi(c2, "Action types", str(len(actions)), "distinct")
    _kpi(c3, "Actors", str(len(actors)), "orchestrator / graph_builder / etc.")
    _kpi(c4, "Reviews pending", str(len(review_tier_items)),
         "entity merges needing analyst approval" if review_tier_items else "none — all auto-merges")

    st.markdown("")

    # ----- Pending merge proposals (actionable) -----
    st.markdown("### 🟡 Pending entity-merge proposals")
    st.caption(
        "Score 80-84 — between auto-merge (≥85) and keep-separate (<80). "
        "Approve to fold the variant into the keeper (edges re-pointed, "
        "alias appended). Reject to remember they're intentionally separate "
        "(future batches won't re-propose)."
    )
    proposals = _fetch_merge_proposals(tenant_id, status_filter="pending")
    if not proposals:
        st.success("No pending merge proposals.")
    else:
        for prop in proposals[:20]:
            cols = st.columns([4, 1, 1])
            cols[0].markdown(
                f"**{prop['node_type']}** · "
                f"`{prop['proposed_key']}` → `{prop['matched_key']}` "
                f"(score {prop['score']:.1f}) · {prop['created_at']}"
            )
            if cols[1].button("Approve", key=f"approve_{prop['id']}", type="primary"):
                result = _post_merge_decision(tenant_id, prop['id'], "approve")
                if result:
                    st.success(f"Merged: {result.get('source_id', '')[:8]} → "
                               f"{result.get('target_id', '')[:8]}")
                    st.rerun()
            if cols[2].button("Reject", key=f"reject_{prop['id']}"):
                result = _post_merge_decision(tenant_id, prop['id'], "reject")
                if result:
                    st.info("Rejected — won't be re-proposed.")
                    st.rerun()

    # ----- Filters -----
    st.markdown("### All events")
    f1, f2, f3 = st.columns([2, 2, 1])
    sel_actions = f1.multiselect("Action", actions, default=actions)
    sel_actors = f2.multiselect("Actor", actors, default=actors)
    keyword = f3.text_input("Search", placeholder="filename, id …")

    mask = df["action"].isin(sel_actions) & df["actor"].isin(sel_actors)
    df_view = df[mask].copy()
    if keyword:
        kl = keyword.lower()
        df_view = df_view[
            df_view.apply(
                lambda r: kl in str(r.get("object_id") or "").lower()
                          or kl in str(r.get("payload") or "").lower(),
                axis=1,
            )
        ]

    # Show as table (drop the heavy payload column from the table; expand-per-row below)
    table_df = df_view[["created_at", "actor", "action", "object_type", "object_id"]].copy()
    st.dataframe(table_df, use_container_width=True, hide_index=True)

    # ----- Per-row drill-in -----
    if len(df_view):
        st.markdown("### Drill into a row")
        idx_options = [
            f"{r['created_at']} · {r['action']} · {(r.get('object_id') or '')[:8]}"
            for _, r in df_view.iterrows()
        ]
        choice = st.selectbox("Pick an audit event", idx_options, key="audit_pick")
        idx = idx_options.index(choice)
        rowd = df_view.iloc[idx].to_dict()
        st.json({k: v for k, v in rowd.items() if k != "raw"})

    # ----- Exports -----
    col_csv, col_json = st.columns(2)
    col_csv.download_button(
        "⬇ Audit CSV",
        data=df_view.drop(columns=["payload"], errors="ignore").to_csv(index=False).encode("utf-8"),
        file_name=f"mdi_audit_{tenant_id[:8]}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    col_json.download_button(
        "⬇ Audit JSON",
        data=df_view.to_json(orient="records", indent=2).encode("utf-8"),
        file_name=f"mdi_audit_{tenant_id[:8]}.json",
        mime="application/json",
        use_container_width=True,
    )


# ---------------------------------------------------------------------------
# Tab: Chat
# ---------------------------------------------------------------------------
def tab_chat(tenant_id: str) -> None:
    st.markdown('<div class="mdi-hero">Chat</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="mdi-sub">Ask about your data. Relationship questions are graph-routed (sub-100ms). Synthesis questions go to the LLM.</div>',
        unsafe_allow_html=True,
    )

    history = st.session_state.setdefault("chat_history", [])
    for turn in history:
        with st.chat_message(turn["role"]):
            st.write(turn["content"])

    q = st.chat_input("e.g. 'list all vendors' or 'what are the trends in spend?'")
    if not q:
        return
    history.append({"role": "user", "content": q})
    with st.chat_message("user"):
        st.write(q)
    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            ans = asyncio.run(_chat_async(tenant_id, q, history))
        st.write(ans["answer"])
        meta = f"route: `{ans['route']}` · {ans['elapsed_ms']}ms"
        if ans.get("citations"):
            meta += f" · {len(ans['citations'])} citation(s)"
        st.caption(meta)
        if ans.get("citations"):
            with st.expander("📎 Cited document chunks"):
                for cid in ans["citations"][:5]:
                    st.code(str(cid))
    history.append({"role": "assistant", "content": ans["answer"]})


# ---------------------------------------------------------------------------
# Tab: Settings — provider routing, cost, RLS check
# ---------------------------------------------------------------------------
def tab_settings(tenant_id: str) -> None:
    st.markdown('<div class="mdi-hero">Settings</div>', unsafe_allow_html=True)

    s = get_settings()
    st.markdown("### Provider routing policy")
    chains = provider_router.describe()
    chain_rows = []
    for tier, chain in chains.items():
        chain_rows.append({
            "Tier": tier,
            "Primary": f"{chain[0][0]} / {chain[0][1]}",
            "Fallback": f"{chain[1][0]} / {chain[1][1]}" if len(chain) > 1 else "(none)",
        })
    st.dataframe(pd.DataFrame(chain_rows), use_container_width=True, hide_index=True)

    st.markdown("### Cost ceilings")
    c1, c2, c3 = st.columns(3)
    _kpi(c1, "Daily cap", f"${s.daily_spend_cap_usd:.2f}", "global")
    _kpi(c2, "Soft warn", f"{int(s.cost_soft_warn_pct * 100)}%", "of cap")
    _kpi(c3, "Hard cap", f"{int(s.cost_hard_cap_pct * 100)}%", "of cap")

    # --- Embedder ---
    st.markdown("### Embedder")
    from mdi.brain.hippocampus import embedder_status
    es = embedder_status()
    e1, e2, e3 = st.columns(3)
    _kpi(e1, "Mode", es["mode"], "stub = SHA-based · real = bge-m3")
    _kpi(e2, "Model", es["model"], f"device: {es['device']}")
    loaded_label = "loaded" if es["loaded"] else ("loading…" if es["loading"] else "cold")
    _kpi(e3, "State", loaded_label,
         "first use takes ~30s" if not es["loaded"] else "ready")

    if es["mode"] == "stub":
        st.info(
            "Stub embedder is active. Memory hits only fire on **identical** "
            "inputs, so the self-training loop won't generalise across vendor-name "
            "variants on real data. Set `USE_REAL_EMBEDDINGS=true` in `.env` and "
            "restart to enable semantic memory."
        )
    else:
        st.caption(
            "Real embedder is active. The first encode loads bge-m3 (~2GB, ~30s) "
            "and stays cached in process memory for the rest of the session."
        )
        if (
            not es["loaded"] and not es["loading"]
            and st.button("🔥 Warm the model now", type="secondary",
                          help="Pay the cold-start cost now instead of letting the "
                               "next upload absorb it.")
        ):
                with st.spinner("Loading bge-m3 (~30s on CPU, faster on GPU)…"):
                    import httpx
                    try:
                        r = httpx.post(
                            "http://127.0.0.1:8080/admin/embeddings/warm",
                            headers={"X-Admin-Key": s.admin_api_key},
                            timeout=180.0,
                        )
                        if r.status_code == 200:
                            data = r.json()
                            if data.get("already_loaded"):
                                st.success("Model was already loaded.")
                            else:
                                st.success(
                                    f"✓ Loaded in {data.get('loaded_in_ms', 0) / 1000:.1f}s"
                                )
                            st.rerun()
                        else:
                            st.error(f"Warm failed: HTTP {r.status_code} · {r.text[:200]}")
                    except httpx.HTTPError as e:
                        st.error(f"API unreachable: {e}")

    st.markdown("### Models")
    st.json({
        "gemini_flash": s.gemini_model_flash,
        "gemini_pro": s.gemini_model_pro,
        "claude_haiku": s.claude_model_haiku,
        "claude_sonnet": s.claude_model_sonnet,
        "claude_opus": s.claude_model_opus,
        "embed_model": s.embed_model,
    })

    st.markdown("### Quality gates")
    st.markdown(
        _badge("RLS via mdi_app role", "ok") +
        _badge(f"Conscience.invent: {'ON' if s.enable_invented_rules else 'gated OFF'}", "warn" if s.enable_invented_rules else "info") +
        _badge(f"Entity merge threshold: {s.entity_resolver_threshold}%", "info"),
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
def _run_query(tenant_id: str, sql: str, **params: Any) -> list[dict[str, Any]]:
    """Execute a parameterised query inside a tenant session and return dicts."""
    from sqlalchemy import text

    async def go() -> list[dict[str, Any]]:
        async with tenant_session(tenant_id) as db:
            res = await db.execute(text(sql), params)
            return [dict(r._mapping) for r in res]

    try:
        return asyncio.run(go())
    except Exception as e:
        st.error(f"DB unreachable: {e}")
        return []


def _fetch_dashboard_counts(tenant_id: str) -> dict[str, Any]:
    counts = {"documents": 0, "patterns": 0, "kg_nodes": 0, "kg_edges": 0, "cost_usd": 0.0}
    try:
        rows = _run_query(tenant_id, """
            SELECT
              (SELECT COUNT(*) FROM documents) AS docs,
              (SELECT COUNT(*) FROM patterns) AS patterns,
              (SELECT COUNT(*) FROM kg_nodes) AS nodes,
              (SELECT COUNT(*) FROM kg_edges) AS edges,
              (SELECT COALESCE(SUM(cost_usd), 0) FROM batches) AS cost
        """)
        if rows:
            r = rows[0]
            counts["documents"] = int(r.get("docs") or 0)
            counts["patterns"] = int(r.get("patterns") or 0)
            counts["kg_nodes"] = int(r.get("nodes") or 0)
            counts["kg_edges"] = int(r.get("edges") or 0)
            counts["cost_usd"] = float(r.get("cost") or 0)
    except Exception:
        pass
    return counts


def _fetch_batches(tenant_id: str, limit: int = 10) -> list[dict[str, Any]]:
    rows = _run_query(tenant_id, """
        SELECT
          id::text AS batch_id,
          status,
          total_documents AS docs,
          ROUND(cost_usd::numeric, 5) AS cost_usd,
          started_at,
          finished_at
        FROM batches
        ORDER BY started_at DESC
        LIMIT :limit
    """, limit=limit)
    return rows


def _fetch_all_extractions(tenant_id: str) -> list[dict[str, Any]]:
    rows = _run_query(tenant_id, """
        SELECT d.id::text AS doc_id, d.filename,
               d.cluster->>'industry' AS industry,
               d.cluster->>'vendor'   AS vendor,
               d.cluster->>'doc_type' AS doc_type,
               (d.cluster->>'confidence')::float AS confidence,
               e.fields
        FROM documents d
        JOIN extractions e ON e.document_id = d.id
        ORDER BY d.created_at DESC
    """)
    out = []
    for r in rows:
        cluster = {"industry": r["industry"], "vendor": r["vendor"],
                   "doc_type": r["doc_type"], "confidence": r["confidence"]}
        ex = {"fields": r["fields"] or {}}
        flat = _flatten_extraction(r["filename"], r["doc_id"], cluster, ex)
        out.append(flat)
    return out


def _fetch_graph(tenant_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes = _run_query(tenant_id, "SELECT id::text AS id, node_type, canonical_key FROM kg_nodes")
    edges = _run_query(tenant_id, "SELECT src_id::text AS src_id, dst_id::text AS dst_id, edge_type FROM kg_edges")
    return nodes, edges


def _fetch_merge_proposals(tenant_id: str, status_filter: str = "pending") -> list[dict[str, Any]]:
    """Tenant-scoped merge-proposal list via the per-tenant API key.

    Falls back to a direct DB query when the API server isn't reachable so
    the UI stays useful in pure-Streamlit local mode.
    """
    import httpx
    try:
        # In local mode the Streamlit UI doesn't authenticate to the API
        # the same way an external client does — use the DB fallback path.
        raise httpx.ConnectError("local-mode-fallback")
    except httpx.HTTPError:
        rows = _run_query(tenant_id, """
            SELECT id::text AS id, node_type, proposed_key, matched_key,
                   score, status, decided_by,
                   to_char(decided_at, 'YYYY-MM-DD HH24:MI:SS') AS decided_at,
                   to_char(created_at, 'YYYY-MM-DD HH24:MI:SS') AS created_at
            FROM entity_merge_proposals
            WHERE (:s = 'all' OR status = :s)
            ORDER BY created_at DESC
            LIMIT 100
        """, s=status_filter)
        return rows


def _post_merge_decision(tenant_id: str, proposal_id: str, decision: str) -> dict[str, Any] | None:
    """Execute the merge / rejection inside the UI's local pipeline path.

    Bypasses the HTTP API for simplicity in local-only mode.
    """
    import asyncio

    from sqlalchemy import text as _sa_text

    from mdi.brain.knowledge_graph import KnowledgeGraph

    async def _run():
        from mdi.kernel.auth import reset_engine
        reset_engine()
        async with tenant_session(tenant_id) as db:
            row = (await db.execute(_sa_text(
                "SELECT node_type, proposed_key, matched_key, status "
                "FROM entity_merge_proposals WHERE id = :id"
            ), {"id": proposal_id})).first()
            if row is None:
                return {"error": "not found"}
            if row.status != "pending":
                return {"error": f"already {row.status}"}

            if decision == "approve":
                kg = KnowledgeGraph(db)
                result = await kg.merge_nodes(
                    tenant_id=uuid.UUID(tenant_id),
                    node_type=row.node_type,
                    source_canonical_key=row.proposed_key,
                    target_canonical_key=row.matched_key,
                )
                if not result.get("merged"):
                    return {"error": result.get("reason")}
                await db.execute(_sa_text(
                    "UPDATE entity_merge_proposals SET status='approved', "
                    "decided_by='analyst-ui', decided_at=NOW() WHERE id = :id"
                ), {"id": proposal_id})
                await db.commit()
                return result
            else:  # reject
                await db.execute(_sa_text(
                    "UPDATE entity_merge_proposals SET status='rejected', "
                    "decided_by='analyst-ui', decided_at=NOW() WHERE id = :id"
                ), {"id": proposal_id})
                await db.commit()
                return {"rejected": True}

    result = asyncio.run(_run())
    if "error" in result:
        st.error(result["error"])
        return None
    return result


def _admin_list_tenants(admin_key: str) -> list[dict[str, Any]] | None:
    import httpx
    try:
        r = httpx.get("http://localhost:8080/admin/tenants",
                      headers={"X-Admin-Key": admin_key}, timeout=5.0)
        if r.status_code != 200:
            st.error(f"List tenants failed: HTTP {r.status_code} — {r.text[:160]}")
            return None
        return r.json().get("tenants", [])
    except httpx.HTTPError as e:
        st.warning(f"Admin API unreachable — start it with `mdi-api`. ({e})")
        return None


def _admin_create_tenant(admin_key: str, *, slug: str, name: str,
                          cap: float, pack_slug: str | None) -> dict[str, Any] | None:
    import httpx
    try:
        r = httpx.post(
            "http://localhost:8080/admin/tenants",
            headers={"X-Admin-Key": admin_key},
            json={"slug": slug, "display_name": name,
                  "monthly_cost_cap_usd": cap, "pack_slug": pack_slug},
            timeout=10.0,
        )
        if r.status_code != 200:
            st.error(f"Create failed: HTTP {r.status_code} — {r.text[:200]}")
            return None
        return r.json()
    except httpx.HTTPError as e:
        st.error(f"Admin API unreachable: {e}")
        return None


def _admin_get_pack(admin_key: str, slug: str) -> dict[str, Any] | None:
    """Fetch the resolved pack manifest. None on failure."""
    import httpx
    try:
        r = httpx.get(f"http://localhost:8080/admin/packs/{slug}",
                      headers={"X-Admin-Key": admin_key}, timeout=5.0)
        if r.status_code != 200:
            st.warning(f"Could not load pack {slug!r}: HTTP {r.status_code}")
            return None
        return r.json()
    except httpx.HTTPError as e:
        st.warning(f"Admin API unreachable: {e}")
        return None


def _render_pack_viewer(pack: dict[str, Any]) -> None:
    """Render a resolved-manifest dict as collapsible sections."""
    head_cols = st.columns([2, 1, 1])
    head_cols[0].markdown(f"**`{pack['slug']}`** · v{pack['version']}")
    head_cols[1].markdown(_badge(f"{len(pack.get('field_schema', {}).get('fields') or [])} fields", "info"),
                          unsafe_allow_html=True)
    head_cols[2].markdown(_badge(f"{len(pack.get('validators') or [])} validators", "info"),
                          unsafe_allow_html=True)
    if pack.get("description"):
        st.caption(pack["description"])

    fields = (pack.get("field_schema") or {}).get("fields") or []
    if fields:
        with st.expander(f"📋 Field schema ({len(fields)})", expanded=False):
            st.dataframe(pd.DataFrame(fields), use_container_width=True, hide_index=True)
            pks = (pack.get("field_schema") or {}).get("primary_keys") or []
            if pks:
                st.caption("Primary keys: " + ", ".join(f"`{k}`" for k in pks))

    doc_types = (pack.get("doc_type_taxonomy") or {}).get("doc_types") or {}
    if doc_types:
        with st.expander(f"🏷 Doc-type taxonomy ({len(doc_types)})", expanded=False):
            rows = [{"doc_type": k, "aliases": ", ".join(v.get("aliases", []) or [])}
                    for k, v in doc_types.items()]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    prompts = pack.get("extract_prompts") or {}
    if prompts:
        with st.expander(f"💬 Extract prompts ({len(prompts)})", expanded=False):
            for doc_type, body in prompts.items():
                st.markdown(f"**`{doc_type}`**")
                st.code(body or "(empty)", language="markdown")

    validators = pack.get("validators") or []
    if validators:
        with st.expander(f"✅ Validators ({len(validators)})", expanded=False):
            st.dataframe(pd.DataFrame(validators), use_container_width=True, hide_index=True)

    merge_rules = pack.get("merge_rules")
    if merge_rules:
        with st.expander("🔀 Merge rules", expanded=False):
            st.json(merge_rules)

    signals = pack.get("classifier_signals")
    if signals:
        with st.expander("🎯 Classifier signals", expanded=False):
            st.json(signals)

    compliance = pack.get("compliance")
    if compliance:
        with st.expander("🛡 Compliance rules", expanded=False):
            st.json(compliance)

    enrichment = pack.get("enrichment") or {}
    if enrichment.get("domain_codes") or enrichment.get("alias_map"):
        with st.expander("🧩 Enrichment dictionaries", expanded=False):
            if enrichment.get("domain_codes"):
                st.caption("Domain codes")
                st.json(enrichment["domain_codes"])
            if enrichment.get("alias_map"):
                st.caption("Alias map")
                st.json(enrichment["alias_map"])

    if pack.get("golden_seed_path"):
        st.caption(f"Golden seed: `{pack['golden_seed_path']}`")


def _admin_list_packs(admin_key: str) -> list[str]:
    """Return available pack slugs via the admin API; empty list on failure."""
    import httpx
    try:
        r = httpx.get("http://localhost:8080/admin/packs",
                      headers={"X-Admin-Key": admin_key}, timeout=5.0)
        if r.status_code != 200:
            return []
        return r.json().get("packs", []) or []
    except httpx.HTTPError:
        return []


def _admin_update_tenant(admin_key: str, tenant_id: str,
                          **changes: Any) -> dict[str, Any] | None:
    """PATCH a tenant. Only non-None fields are sent."""
    import httpx
    body = {k: v for k, v in changes.items() if v is not None}
    try:
        r = httpx.patch(
            f"http://localhost:8080/admin/tenants/{tenant_id}",
            headers={"X-Admin-Key": admin_key},
            json=body, timeout=10.0,
        )
        if r.status_code != 200:
            st.error(f"Update failed: HTTP {r.status_code} — {r.text[:200]}")
            return None
        return r.json()
    except httpx.HTTPError as e:
        st.error(f"Admin API unreachable: {e}")
        return None


def _admin_issue_key(admin_key: str, *, tenant_id: str, label: str) -> dict[str, Any] | None:
    import httpx
    try:
        r = httpx.post(
            f"http://localhost:8080/admin/tenants/{tenant_id}/api_keys",
            headers={"X-Admin-Key": admin_key},
            json={"label": label}, timeout=10.0,
        )
        if r.status_code != 200:
            st.error(f"Issue key failed: HTTP {r.status_code} — {r.text[:200]}")
            return None
        return r.json()
    except httpx.HTTPError as e:
        st.error(f"Admin API unreachable: {e}")
        return None


def _fetch_audit(tenant_id: str, limit: int = 500) -> list[dict[str, Any]]:
    return _run_query(tenant_id, """
        SELECT actor, action, object_type, object_id, payload,
               to_char(created_at, 'YYYY-MM-DD HH24:MI:SS') AS created_at
        FROM audit_log
        ORDER BY created_at DESC
        LIMIT :limit
    """, limit=limit)


def _fetch_patterns(tenant_id: str) -> list[dict[str, Any]]:
    rows = _run_query(tenant_id, """
        SELECT industry, vendor, doc_type, seen_count,
               jsonb_array_length(COALESCE(schema_def->'fields', '[]'::jsonb)) AS field_count,
               last_seen_at
        FROM patterns
        ORDER BY last_seen_at DESC
    """)
    return rows


async def _chat_async(tenant_id: str, question: str, history: list[dict]) -> dict[str, Any]:
    from mdi.brain.chat import chat as chat_layer
    from mdi.brain.knowledge_graph import KnowledgeGraph
    from mdi.models.schemas import ChatRequest, ChatTurn

    reset_gateway()
    reset_providers()
    reset_engine()
    async with tenant_session(tenant_id) as db:
        kg = KnowledgeGraph(db)
        req = ChatRequest(
            question=question,
            history=[ChatTurn(role=h["role"], content=h["content"]) for h in history[-6:]],
        )
        resp = await chat_layer(kg=kg, request=req)
    return {
        "answer": resp.answer,
        "route": resp.route,
        "elapsed_ms": resp.elapsed_ms,
        "citations": [str(c) for c in (resp.citations or [])],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    tenant_id = render_sidebar()

    tabs = st.tabs([
        "🏠 Dashboard",
        "⬆ Upload",
        "📊 Results",
        "🕸 Knowledge Graph",
        "🧬 Patterns",
        "✅ EvalLayers",
        "📜 Audit Log",
        "💬 Chat",
        "🔐 Admin",
        "⚙ Settings",
    ])
    with tabs[0]:
        tab_dashboard(tenant_id)
    with tabs[1]:
        tab_upload(tenant_id)
    with tabs[2]:
        tab_results(tenant_id)
    with tabs[3]:
        tab_graph(tenant_id)
    with tabs[4]:
        tab_patterns(tenant_id)
    with tabs[5]:
        tab_evals(tenant_id)
    with tabs[6]:
        tab_audit(tenant_id)
    with tabs[7]:
        tab_chat(tenant_id)
    with tabs[8]:
        tab_admin()
    with tabs[9]:
        tab_settings(tenant_id)


def run() -> None:
    """`mdi-ui` console entrypoint — wraps `streamlit run`."""
    import streamlit.web.cli as stcli

    sys.argv = ["streamlit", "run", str(_THIS), "--server.headless=true"]
    sys.exit(stcli.main())


if __name__ == "__main__":
    main()