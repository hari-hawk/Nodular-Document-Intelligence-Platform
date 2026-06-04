"""Coverage classifier (Stage 13).

Given DocumentGroups produced by the orchestrator's group discovery
(Stage 12), classify each as full / partial / orphan based on which
doc-type slots are populated.

Heuristics:
  full     — at least one of {invoice, statement, receipt} AND a contract or PO
  partial  — has docs but missing the contract/PO anchor
  orphan   — single document; no shared identifiers with others
"""
from __future__ import annotations

from collections import defaultdict

from mdi.models.schemas import (
    Cluster,
    DocumentGroup,
    Extraction,
)


def classify_groups(
    groups: list[DocumentGroup],
    extractions: dict[str, Extraction],  # str(doc_id) -> Extraction
    clusters: dict[str, Cluster],
) -> list[DocumentGroup]:
    out: list[DocumentGroup] = []
    for g in groups:
        types_seen: set[str] = set()
        for did in g.document_ids:
            c = clusters.get(str(did))
            if c is not None:
                types_seen.add(c.doc_type)

        if len(g.document_ids) <= 1:
            coverage = "orphan"
        else:
            anchor = bool(types_seen & {"contract", "purchase_order"})
            settle = bool(types_seen & {"invoice", "statement", "receipt"})
            if anchor and settle:
                coverage = "full"
            else:
                coverage = "partial"
        out.append(g.model_copy(update={"coverage": coverage}))
    return out


def discover_groups(
    extractions: dict[str, Extraction],
    *,
    keys: tuple[str, ...] = ("account_number", "contract_id", "customer", "patient_id"),
) -> list[DocumentGroup]:
    """Stage 12 — group documents by shared identifiers."""
    buckets: dict[tuple[str, str], list[str]] = defaultdict(list)
    for doc_id_str, ex in extractions.items():
        for k in keys:
            f = ex.fields.get(k)
            if f and f.value:
                buckets[(k, str(f.value))].append(doc_id_str)

    groups: list[DocumentGroup] = []
    used: set[str] = set()
    counter = 0
    for (k, v), members in buckets.items():
        unique = sorted(set(members))
        if len(unique) < 2:
            continue
        counter += 1
        groups.append(
            DocumentGroup(
                group_id=f"grp-{counter}",
                shared_keys={k: v},
                document_ids=[__import__("uuid").UUID(d) for d in unique],
            )
        )
        used.update(unique)

    # Orphans
    for doc_id_str in extractions.keys():
        if doc_id_str in used:
            continue
        counter += 1
        groups.append(
            DocumentGroup(
                group_id=f"grp-{counter}",
                shared_keys={},
                document_ids=[__import__("uuid").UUID(doc_id_str)],
            )
        )
    return groups
