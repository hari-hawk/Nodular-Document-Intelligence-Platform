"""Real embedder semantic-similarity assertion.

This test exists to validate the claim: with the real BAAI/bge-m3 model,
vendor-name variants ("AT&T" vs "AT&T Business Services") embed close
enough in cosine space to trip the SIMILARITY_THRESHOLD (0.82) — which
is the entire point of the self-training loop on real data.

Skipped by default because loading bge-m3 takes ~30s and downloads ~2GB.
Opt in with:

    USE_REAL_EMBEDDINGS=true pytest --run-live -m live_llm tests/live_llm/test_real_embeddings.py
"""
from __future__ import annotations

import os
import pytest


pytestmark = pytest.mark.live_llm


def _bool_env(name: str) -> bool:
    return os.environ.get(name, "").lower() in ("1", "true", "yes", "on")


def test_real_embeddings_capture_vendor_variants(reset_runtime) -> None:
    if not _bool_env("USE_REAL_EMBEDDINGS"):
        pytest.skip(
            "set USE_REAL_EMBEDDINGS=true to opt into the real bge-m3 test"
            " (downloads ~2GB on first run)"
        )

    # Import here so the module load doesn't pull sentence-transformers
    # for the skip path.
    from mdi.brain.hippocampus import _Embedder, SIMILARITY_THRESHOLD

    real = _Embedder(use_real_model=True)
    # First call triggers the load (covered by reset_runtime + 30s budget).
    e1 = real.embed("telecom | AT&T | invoice | layout=tabular")
    e2 = real.embed("telecom | AT&T Business Services | invoice | layout=tabular")

    # Cosine similarity over normalised unit vectors == dot product.
    sim = sum(a * b for a, b in zip(e1, e2))
    print(f"\n[real_embeddings] cosine('AT&T', 'AT&T Business Services') = {sim:.4f}"
          f"  (threshold {SIMILARITY_THRESHOLD})")
    assert sim >= SIMILARITY_THRESHOLD, (
        f"real bge-m3 should treat 'AT&T' and 'AT&T Business Services' as "
        f"the same scope (cosine ≥ {SIMILARITY_THRESHOLD}), got {sim:.4f}"
    )

    # And a sanity counter-example: unrelated vendors should NOT collapse.
    e3 = real.embed("telecom | Verizon | invoice | layout=tabular")
    diff_sim = sum(a * b for a, b in zip(e1, e3))
    print(f"[real_embeddings] cosine('AT&T', 'Verizon')               = {diff_sim:.4f}")
    assert diff_sim < sim, (
        "AT&T and Verizon should be less similar than AT&T variants"
    )
