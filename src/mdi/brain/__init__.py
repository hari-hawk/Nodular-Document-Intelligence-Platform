"""Brain — 7 cognitive organs + 7 supporting layers.

Organs:
  Eyes          — open-vocabulary classification (Gemini 2.5 Flash)
  Hippocampus   — pgvector pattern + correction memory
  Pattern Cortex — autonomous schema discovery (Gemini 2.5 Pro, skipped on memory hit)
  Conscience    — type-derived baseline rules + optional invented rules + simpleeval validation
  Hands         — extraction with vision routing + correction injection (Gemini 2.5 Flash + Vision)
  Inner Voice   — per-pattern strong/watch/weak verdicts (pure Python)
  Insight Cortex — six analysis types: trends · cross-doc · peer · pattern · risk · optimization

Supporting layers:
  Coverage classifier · Account Briefing · Narrator · Chat ·
  Knowledge Graph · Graph Builder · Entity Resolver
"""
