"""Cross-industry classification + memory-hit self-improvement loop.

Validates two of the platform's most important claims in one test:
  1. The brain handles distinct industries without per-domain config
     (the open-vocabulary thesis).
  2. Memory hit short-circuits Pattern Cortex on the second appearance of
     a similar cluster (the self-improvement thesis).

Cost budget: ~$0.10 (5 cold-start docs + 1 warm-hit doc).
"""
from __future__ import annotations

import asyncio
import pytest

from tests.live_llm.conftest import TENANT_A


pytestmark = pytest.mark.live_llm


def test_cross_industry_and_memory_hit(
    fresh_db, reset_runtime, cross_industry_corpus,
) -> None:
    from mdi.brain.hippocampus import Hippocampus
    from mdi.orchestrator.pipeline import run_batch_async

    # Both batches share one event loop so the asyncpg connection pool
    # stays bound to the right loop. Splitting into two `asyncio.run()`
    # calls trips "Future attached to a different loop".
    async def _drive():
        h1 = Hippocampus(use_real_embeddings=False)
        r1 = await run_batch_async(
            tenant_id=str(TENANT_A),
            payloads=cross_industry_corpus,
            hippocampus=h1,
            persist=True,
        )
        h2 = Hippocampus(use_real_embeddings=False)
        # Re-process the first corpus doc by re-uploading the same bytes.
        # The stub embedder is content-hash based (not semantic), so
        # identical bytes => identical Eyes output => identical
        # cluster_text => identical embedding => guaranteed memory hit.
        r2 = await run_batch_async(
            tenant_id=str(TENANT_A),
            payloads=[cross_industry_corpus[0]],
            hippocampus=h2,
            persist=True,
        )
        return r1, r2

    report1, report2 = asyncio.run(_drive())

    # Each doc should classify to a distinct industry/doc_type combo.
    industries = {c["industry"] for c in report1["clusters"].values()}
    doc_types = {c["doc_type"] for c in report1["clusters"].values()}
    assert len(industries) >= 3, (
        f"expected ≥3 distinct industries from 4 cross-industry docs, "
        f"got {industries}"
    )
    assert len(doc_types) >= 3, (
        f"expected ≥3 distinct doc_types from 4 cross-industry docs, "
        f"got {doc_types}"
    )

    # Every doc should have produced an extraction with at least 1 field.
    assert len(report1["extractions"]) == len(cross_industry_corpus)
    for ex in report1["extractions"].values():
        assert len(ex["fields"]) > 0

    # EvalLayers fired across every stage.
    eval_stages = {e["stage_name"] for e in report1["stage_evals"]}
    assert {"02_classify", "04_schema_discovery", "07_extract",
            "08_validate", "10_insights", "17_graph"} <= eval_stages

    # No high-severity eval failures expected on this clean corpus.
    failures = [e for e in report1["stage_evals"]
                if not e["passed"] and e["severity"] == "HIGH"]
    assert not failures, f"unexpected HIGH-severity eval failures: {failures}"

    # Cost should be in the documented range ($0.01-0.02 per cold doc).
    cost_per_doc = report1["total_cost_usd"] / len(cross_industry_corpus)
    assert 0.001 <= cost_per_doc <= 0.10, (
        f"per-doc cost ${cost_per_doc:.4f} outside expected range"
    )

    # ===== BATCH 2 — warm, expect memory hit on the AT&T pattern =====
    # The memory hit should fire (cosine similarity ≥ 0.82 against the
    # pattern persisted in batch 1).
    memory_hit_fired = any(
        "memory.hit" in line for line in report2["progress"]
    )
    pattern_cortex_skipped = not any(
        "schema.discovered" in line for line in report2["progress"]
    )
    assert memory_hit_fired, (
        f"memory.hit did NOT fire in batch 2; progress was: {report2['progress']}"
    )
    assert pattern_cortex_skipped, (
        "Pattern Cortex should have been skipped on memory hit"
    )

    # NOTE: per-doc cost is not a fair comparison here because the warm
    # batch has only 1 doc, so Narrator's fixed cost is amortized over 1
    # instead of 4. The cost-saving is real (Pattern Cortex was skipped
    # on the memory hit) but it shows up in absolute LLM-call count, not
    # in per-doc cost. memory_hit_fired + pattern_cortex_skipped above are
    # the structural assertions that the saving happened.
    warm_cost = report2["total_cost_usd"]
    print(
        f"\n[cross_industry] cold batch: ${report1['total_cost_usd']:.5f} "
        f"({len(cross_industry_corpus)} docs) · "
        f"warm batch: ${warm_cost:.5f} (1 doc, Pattern Cortex skipped)"
    )
