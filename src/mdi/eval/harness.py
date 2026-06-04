"""Evaluation harness - golden datasets + per-pack accuracy.

Golden file layout (per pack)::

    pack: business_documents_base
    accuracy_target: 0.90
    cases:
      - filename: invoice_001.pdf
        expected:
          vendor: "Acme Corp"
          total: 1234.56
          currency: USD

Usage::

    from mdi.eval.harness import run_evaluation
    summary = await run_evaluation("business_documents_base")
    assert summary.precision_at_extractable >= 0.90
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from mdi.kernel.observability import get_logger
from mdi.kernel.settings import get_settings
from mdi.orchestrator.pipeline import run_batch_async

logger = get_logger(__name__)


@dataclass
class FieldResult:
    expected: Any
    actual: Any
    match: bool


@dataclass
class CaseResult:
    filename: str
    fields: dict[str, FieldResult] = field(default_factory=dict)
    extra_fields: int = 0
    missing_fields: int = 0


@dataclass
class EvalSummary:
    pack: str
    target: float
    cases: list[CaseResult] = field(default_factory=list)

    @property
    def total_expected(self) -> int:
        return sum(len(c.fields) for c in self.cases)

    @property
    def total_correct(self) -> int:
        return sum(1 for c in self.cases for f in c.fields.values() if f.match)

    @property
    def precision_at_extractable(self) -> float:
        if not self.total_expected:
            return 0.0
        return self.total_correct / self.total_expected


def _norm(v: Any) -> str:
    return str(v).strip().lower() if v is not None else ""


async def run_evaluation(
    pack_slug: str,
    *,
    golden_dir: Path | None = None,
    tenant_id: str | None = None,
    persist: bool = False,
) -> EvalSummary:
    s = get_settings()
    base = golden_dir or (s.package_root / "eval" / "golden" / pack_slug)
    golden_path = base / "golden.yaml"
    if not golden_path.exists():
        raise FileNotFoundError(f"missing golden YAML for pack {pack_slug}: {golden_path}")
    spec = yaml.safe_load(golden_path.read_text(encoding="utf-8"))
    target = float(spec.get("accuracy_target", 0.9))

    payloads: list[dict[str, Any]] = []
    expectations: dict[str, dict[str, Any]] = {}
    for case in spec.get("cases", []):
        path = base / case["filename"]
        if not path.exists():
            logger.warning("eval.missing_file", filename=case["filename"])
            continue
        payloads.append({"filename": case["filename"], "content": path.read_bytes()})
        expectations[case["filename"]] = case.get("expected", {})

    tid = tenant_id or str(uuid4())
    report = await run_batch_async(tenant_id=tid, payloads=payloads, persist=persist)

    summary = EvalSummary(pack=pack_slug, target=target)
    by_filename = {d["filename"]: d for d in report.get("documents", [])}
    extractions_by_doc = {
        doc_id: ex for doc_id, ex in report.get("extractions", {}).items()
    }

    fname_to_ext: dict[str, dict[str, Any]] = {}
    for doc_id, ex in extractions_by_doc.items():
        for fname, doc_meta in by_filename.items():
            if doc_meta.get("document_id") == doc_id:
                fname_to_ext[fname] = ex
                break

    for filename, expected in expectations.items():
        ex = fname_to_ext.get(filename, {})
        ex_fields = ex.get("fields", {}) if isinstance(ex, dict) else {}
        case_result = CaseResult(filename=filename)
        for k, expected_val in expected.items():
            actual_val = (
                ex_fields[k]["value"]
                if isinstance(ex_fields, dict) and k in ex_fields
                else None
            )
            case_result.fields[k] = FieldResult(
                expected=expected_val,
                actual=actual_val,
                match=_norm(expected_val) == _norm(actual_val),
            )
        summary.cases.append(case_result)
    return summary


def cli() -> None:
    """python -m mdi.eval.harness <pack_slug>"""
    import sys

    pack = sys.argv[1] if len(sys.argv) > 1 else "business_documents_base"
    summary = asyncio.run(run_evaluation(pack))
    p = summary.precision_at_extractable
    print(f"{summary.pack}: {summary.total_correct}/{summary.total_expected} = {p:.3f}")
    for c in summary.cases:
        print(f"  {c.filename}: "
              f"{sum(1 for f in c.fields.values() if f.match)}/{len(c.fields)}")
    sys.exit(0 if p >= summary.target else 1)


if __name__ == "__main__":
    cli()
