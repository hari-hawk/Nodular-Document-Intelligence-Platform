"""Live evaluation across every pack's golden seed.

Walks `src/mdi/eval/golden/<pack>/golden.yaml`, runs each listed document
through the full pipeline with REAL Gemini calls, then compares the
extracted fields against the `expected` block. Reports per-pack accuracy
and contrasts it against the pack's declared `accuracy_target`.

This is a one-shot evaluator, not a regression gate — it's intended to
answer the question "how is the platform actually doing on every domain
right now?". It costs real money (~$0.20-1.00 per full run depending on
model mix). Skips cases whose sample file is missing rather than failing.

Usage:
    python scripts/run_golden_eval.py                  # all packs
    python scripts/run_golden_eval.py --pack telecom_billing  # one pack
    python scripts/run_golden_eval.py --no-persist     # don't write to DB
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

# Load .env so live keys flow through to the provider router.
_ROOT = Path(__file__).resolve().parents[1]
_env = _ROOT / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            kk, vv = k.strip(), v.strip()
            if vv:
                os.environ[kk] = vv

# Use the docker-compose port (5532), matching the live tests.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://mdi_app:mdi_app@localhost:5532/mdi",
)
os.environ.setdefault(
    "DATABASE_URL_ADMIN_SYNC",
    "postgresql://mdi:mdi@localhost:5532/mdi",
)
os.environ.setdefault(
    "DATABASE_URL_ADMIN",
    "postgresql+psycopg://mdi:mdi@localhost:5532/mdi",
)

sys.path.insert(0, str(_ROOT / "src"))

# A dedicated tenant for golden-seed evals so we never collide with live tests
# or real tenants. Created on demand via the admin DSN.
GOLDEN_TENANT = uuid.UUID("99999999-9999-9999-9999-999999999999")
GOLDEN_DIR = _ROOT / "src" / "mdi" / "eval" / "golden"


def _ensure_tenant() -> None:
    """Bootstrap (or recreate) the golden tenant + clear any prior eval data."""
    import psycopg

    admin_dsn = os.environ["DATABASE_URL_ADMIN_SYNC"]
    with psycopg.connect(admin_dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SET row_security = off")
        cur.execute(
            "INSERT INTO tenants (id, slug, display_name, config) "
            "VALUES (%s, %s, %s, %s::jsonb) "
            "ON CONFLICT (id) DO UPDATE SET config = EXCLUDED.config",
            (str(GOLDEN_TENANT), "golden-eval", "Golden Seed Eval", "{}"),
        )
        # Truncate prior runs so the same case doesn't accumulate dup memory hits.
        for tbl in (
            "documents", "extractions", "anomalies", "patterns", "corrections",
            "audit_log", "kg_nodes", "kg_edges", "batches", "cost_events",
            "doc_chunks",
        ):
            cur.execute(
                f"DELETE FROM {tbl} WHERE tenant_id = %s",
                (str(GOLDEN_TENANT),),
            )


def _values_match(actual: Any, expected: Any) -> bool:
    """Compare with currency-aware tolerance: floats compare within 1 cent,
    strings compare case-insensitively + whitespace-normalised."""
    if expected is None:
        return actual in (None, "", [])
    if isinstance(expected, (int, float)):
        try:
            return abs(float(actual) - float(expected)) < 0.01
        except (TypeError, ValueError):
            return False
    a = str(actual or "").strip().lower()
    e = str(expected).strip().lower()
    return a == e


def _extract_value(field_block: Any) -> Any:
    """The pipeline emits Extraction.fields[name] as a FieldExtraction dict
    with a `value` key. Tolerate both the dict form and the bare-value form."""
    if isinstance(field_block, dict) and "value" in field_block:
        return field_block["value"]
    return field_block


async def _run_one_case(
    pack: str,
    filename: str,
    expected: dict[str, Any],
    *,
    persist: bool,
) -> dict[str, Any]:
    from mdi.brain.hippocampus import Hippocampus
    from mdi.orchestrator.pipeline import run_batch_async

    path = GOLDEN_DIR / pack / filename
    if not path.exists():
        return {
            "filename": filename, "skipped": True,
            "reason": f"sample file missing: {path}",
        }

    payloads = [{"filename": filename, "content": path.read_bytes()}]
    report = await run_batch_async(
        tenant_id=str(GOLDEN_TENANT),
        payloads=payloads,
        hippocampus=Hippocampus(use_real_embeddings=False),
        persist=persist,
    )

    docs = report.get("documents") or []
    if not docs:
        return {"filename": filename, "skipped": True, "reason": "no document ingested"}
    doc_id = docs[0].get("document_id")
    extractions = report.get("extractions") or {}
    fields = (extractions.get(doc_id) or {}).get("fields") or {}

    per_field: dict[str, dict[str, Any]] = {}
    matches = 0
    for key, exp_val in expected.items():
        got = _extract_value(fields.get(key))
        ok = _values_match(got, exp_val)
        per_field[key] = {"expected": exp_val, "got": got, "match": ok}
        if ok:
            matches += 1

    cluster = (report.get("clusters") or {}).get(doc_id) or {}
    return {
        "filename": filename,
        "skipped": False,
        "industry": cluster.get("industry"),
        "doc_type": cluster.get("doc_type"),
        "vendor": cluster.get("vendor"),
        "matches": matches,
        "total": len(expected),
        "accuracy": matches / len(expected) if expected else 0.0,
        "per_field": per_field,
        "cost_usd": report.get("total_cost_usd", 0.0),
        "anomalies": len(report.get("anomalies") or []),
    }


async def _run_pack(pack: str, *, persist: bool) -> dict[str, Any]:
    spec = yaml.safe_load((GOLDEN_DIR / pack / "golden.yaml").read_text())
    target = float(spec.get("accuracy_target", 0.0))
    cases: list[dict[str, Any]] = spec.get("cases", [])

    case_results: list[dict[str, Any]] = []
    for case in cases:
        case_results.append(
            await _run_one_case(
                pack, case["filename"], case.get("expected", {}),
                persist=persist,
            )
        )

    scored = [c for c in case_results if not c.get("skipped")]
    total_matches = sum(c["matches"] for c in scored)
    total_fields = sum(c["total"] for c in scored)
    accuracy = total_matches / total_fields if total_fields else 0.0
    cost = sum(c.get("cost_usd", 0.0) for c in scored)

    return {
        "pack": pack,
        "accuracy_target": target,
        "accuracy_observed": accuracy,
        "passed_target": accuracy >= target,
        "n_cases": len(case_results),
        "n_scored": len(scored),
        "n_skipped": len(case_results) - len(scored),
        "total_matches": total_matches,
        "total_fields": total_fields,
        "cost_usd": cost,
        "cases": case_results,
    }


async def _main(packs: list[str], *, persist: bool) -> dict[str, Any]:
    if persist:
        _ensure_tenant()

    started = datetime.now(UTC)
    by_pack: list[dict[str, Any]] = []
    for pack in packs:
        print(f"\n=== {pack} ===", flush=True)
        result = await _run_pack(pack, persist=persist)
        by_pack.append(result)
        status = "PASS" if result["passed_target"] else "FAIL"
        print(
            f"  [{status}] accuracy={result['accuracy_observed']:.2%} "
            f"target={result['accuracy_target']:.2%} "
            f"cases={result['n_scored']}/{result['n_cases']} "
            f"cost=${result['cost_usd']:.4f}",
            flush=True,
        )
        for c in result["cases"]:
            if c.get("skipped"):
                print(f"    - {c['filename']}: SKIPPED ({c.get('reason')})", flush=True)
            else:
                print(
                    f"    - {c['filename']}: {c['matches']}/{c['total']} "
                    f"({c['accuracy']:.0%}) [{c.get('industry')}/{c.get('doc_type')}]",
                    flush=True,
                )

    total_cost = sum(p["cost_usd"] for p in by_pack)
    n_passed = sum(1 for p in by_pack if p["passed_target"])

    return {
        "started_at": started.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "n_packs": len(by_pack),
        "n_passed_target": n_passed,
        "total_cost_usd": total_cost,
        "packs": by_pack,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--pack", action="append",
        help="Specific pack to evaluate. Repeatable. Default: all six.",
    )
    ap.add_argument(
        "--no-persist", action="store_true",
        help="Skip DB writes (faster, but no audit trail or memory accumulation).",
    )
    ap.add_argument(
        "--out", type=Path, default=_ROOT / "eval_report.json",
        help="Where to write the full JSON report.",
    )
    args = ap.parse_args()

    requested_packs = args.pack or sorted(p.name for p in GOLDEN_DIR.iterdir() if p.is_dir())
    report = asyncio.run(_main(requested_packs, persist=not args.no_persist))
    args.out.write_text(json.dumps(report, indent=2, default=str))

    print(
        f"\nWrote {args.out} · "
        f"{report['n_passed_target']}/{report['n_packs']} packs hit target · "
        f"total cost ${report['total_cost_usd']:.4f}",
    )
    sys.exit(0 if report["n_passed_target"] == report["n_packs"] else 1)
