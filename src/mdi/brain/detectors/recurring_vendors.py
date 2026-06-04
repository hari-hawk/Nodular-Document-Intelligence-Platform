"""Recurring vendors — which vendors appear across multiple documents in a batch?

Useful as the "this customer's portfolio" view: when a tenant uploads
30 invoices and 18 are from Acme Corp, that's a portfolio concentration
signal worth surfacing.

Signal semantics:
  - 1 document with a vendor      → not a finding (singleton, no concentration)
  - 2+ documents same vendor      → INFO finding ("Acme Corp appears in 4 documents")
  - >= 50% of batch same vendor   → MEDIUM (concentration risk)
  - >= 75% of batch same vendor   → HIGH (over-reliance flag)

The 50% / 75% thresholds are DD's empirically tuned set. They surface
the kind of concentration that procurement teams genuinely flag.
"""
from __future__ import annotations

import uuid
from collections import Counter, defaultdict

from mdi.models.schemas import Cluster, Insight


def detect_recurring_vendors(
    clusters: dict[uuid.UUID, Cluster],
    *,
    min_sightings: int = 2,
    concentration_warn: float = 0.50,
    concentration_high: float = 0.75,
) -> list[Insight]:
    """Return one finding per vendor appearing in >= min_sightings documents.

    Args:
      clusters: document_id → Cluster from the batch
      min_sightings: minimum number of documents before we surface a finding
      concentration_warn: fraction of batch above which severity is MEDIUM
      concentration_high: fraction above which severity is HIGH
    """
    if not clusters:
        return []

    # Normalise vendor names — Eyes is non-deterministic about
    # capitalisation/punctuation ("AT&T" vs "AT&T Business Services").
    # Cheap normalisation here so two near-identical vendors collapse.
    def _norm(v: str) -> str:
        return " ".join(v.lower().split())

    counts: Counter[str] = Counter()
    docs_per_vendor: dict[str, list[str]] = defaultdict(list)
    display_name: dict[str, str] = {}

    for doc_id, cluster in clusters.items():
        if not cluster.vendor or cluster.vendor.lower() == "unknown":
            continue
        norm = _norm(cluster.vendor)
        counts[norm] += 1
        docs_per_vendor[norm].append(str(doc_id))
        # Keep the longest-form display name seen (usually the most descriptive)
        if norm not in display_name or len(cluster.vendor) > len(display_name[norm]):
            display_name[norm] = cluster.vendor

    total_docs = len(clusters)
    findings: list[Insight] = []

    for norm, n in counts.most_common():
        if n < min_sightings:
            continue
        fraction = n / total_docs
        if fraction >= concentration_high:
            severity = "HIGH"
            title = (
                f"{display_name[norm]} dominates this batch "
                f"({n} of {total_docs} docs, {fraction:.0%})"
            )
            body = (
                "Over 75% of documents in this batch come from a single vendor. "
                "Worth confirming that's intentional — concentration this high is "
                "often a data-loading artefact rather than a portfolio truth."
            )
        elif fraction >= concentration_warn:
            severity = "MEDIUM"
            title = (
                f"{display_name[norm]} is the majority vendor "
                f"({n} of {total_docs} docs, {fraction:.0%})"
            )
            body = (
                "Concentration above 50%. Worth confirming with the customer "
                "that the portfolio is genuinely vendor-skewed, not a sampling bias."
            )
        else:
            severity = "INFO"
            title = (
                f"{display_name[norm]} recurs across {n} documents"
            )
            body = (
                f"Seen in {fraction:.0%} of this batch. Useful for cross-doc "
                f"grouping and account briefings."
            )

        findings.append(Insight(
            insight_type="trend",
            severity=severity,  # type: ignore[arg-type]  # narrowed by branches above
            title=title,
            body=body,
            evidence=[],
            affected_documents=[uuid.UUID(d) for d in docs_per_vendor[norm]],
        ))

    return findings
