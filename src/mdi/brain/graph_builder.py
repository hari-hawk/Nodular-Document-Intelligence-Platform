"""Graph builder (Stage 17) — convert a BatchReport's extractions into KG upserts.

Idempotent: re-running on the same batch produces the same edges and nodes.

Entity resolution: before upserting Vendor/Customer/Account nodes, we run
the fuzzy resolver against existing nodes of the same type for this tenant.
If the proposal comes back as `auto` (score >= AUTO_THRESHOLD), the new
key is canonicalised to the existing one — that's how `AT&T` and `AT&T
Business Services` merge to a single Vendor node. `review`-tier proposals
land in the audit log for analyst confirmation.
"""
from __future__ import annotations

import uuid

from sqlalchemy import text as _sql_text
from sqlalchemy.dialects.postgresql import insert as _pg_insert

from mdi.brain.entity_resolver import normalize_vendor_name, propose_match
from mdi.brain.knowledge_graph import KnowledgeGraph
from mdi.kernel.observability import get_logger
from mdi.models.db import AuditEvent, EntityMergeProposal
from mdi.models.schemas import BatchReport, GraphDelta, NodeType

logger = get_logger(__name__)


# Node types that get entity-resolved (high-cardinality, name-varying things).
_RESOLVABLE: set[str] = {"Vendor", "Customer", "Account", "Provider"}


def _str_field(extraction_fields: dict, key: str) -> str | None:
    f = extraction_fields.get(key)
    if f is None or f.value is None:
        return None
    return str(f.value).strip() or None


async def _resolve_canonical_key(
    kg: KnowledgeGraph,
    *,
    tenant_id: uuid.UUID,
    node_type: NodeType,
    proposed_key: str,
) -> tuple[str, str | None]:
    """Return (canonical_key_to_use, merge_note_if_any).

    Behaviour:
      * `auto` decision: merge to existing key (rapidfuzz >= 85).
      * `review` decision (80-84): consult `entity_merge_proposals`.
          - already approved -> treat as auto (rare race; honour the decision)
          - already rejected -> keep separate, NO new proposal written
          - new -> upsert pending proposal, keep separate this batch
      * `reject` decision (<80): keep separate, no proposal.
    """
    if node_type not in _RESOLVABLE:
        return proposed_key, None
    existing = await kg.find_nodes(node_type=node_type, limit=200)
    if not existing:
        return proposed_key, None
    candidates = [n["canonical_key"] for n in existing]
    proposal = propose_match(proposed_key, candidates)
    if proposal is None:
        return proposed_key, None

    if proposal.decision == "auto":
        return proposal.candidate, (
            f"auto-merged: {proposed_key!r} -> {proposal.candidate!r} "
            f"(score={proposal.score:.1f})"
        )

    if proposal.decision == "review":
        # Consult prior analyst decisions for this exact pair.
        prior = (
            await kg.session.execute(
                _sql_text(
                    "SELECT status FROM entity_merge_proposals "
                    "WHERE tenant_id = :tid AND node_type = :nt "
                    "  AND proposed_key = :pk AND matched_key = :mk"
                ),
                {
                    "tid": str(tenant_id), "nt": node_type,
                    "pk": proposed_key, "mk": proposal.candidate,
                },
            )
        ).first()
        if prior is not None:
            if prior.status == "approved":
                return proposal.candidate, (
                    f"analyst-approved merge: {proposed_key!r} -> "
                    f"{proposal.candidate!r}"
                )
            if prior.status == "rejected":
                # Honour the rejection forever — keep separate, no re-propose.
                return proposed_key, None
            # status == "pending" — already queued; don't re-write the row.
            return proposed_key, (
                f"review-tier proposal (queued): {proposed_key!r} ~= "
                f"{proposal.candidate!r} (score={proposal.score:.1f})"
            )

        # First time we see this pair — write a pending proposal.
        stmt = (
            _pg_insert(EntityMergeProposal.__table__)
            .values(
                tenant_id=tenant_id, node_type=node_type,
                proposed_key=proposed_key, matched_key=proposal.candidate,
                score=proposal.score, status="pending",
            )
            .on_conflict_do_nothing(constraint="uq_merge_proposal_pair")
        )
        await kg.session.execute(stmt)
        return proposed_key, (
            f"review-tier proposal: {proposed_key!r} ~= "
            f"{proposal.candidate!r} (score={proposal.score:.1f}); "
            f"queued for analyst decision"
        )

    return proposed_key, None


async def build_graph(
    *,
    kg: KnowledgeGraph,
    tenant_id: uuid.UUID,
    report: BatchReport,
) -> GraphDelta:
    nodes_added = 0
    edges_added = 0
    merges_proposed = 0
    merge_notes: list[str] = []

    async def _resolve_and_upsert(
        node_type: NodeType, raw_key: str, properties: dict,
    ) -> uuid.UUID:
        """Resolve raw_key through the entity resolver, upsert, return id."""
        nonlocal nodes_added, merges_proposed, merge_notes
        canonical, note = await _resolve_canonical_key(
            kg, tenant_id=tenant_id, node_type=node_type, proposed_key=raw_key,
        )
        if note:
            merges_proposed += 1
            merge_notes.append(note)
            logger.info("kg.entity_resolution", node_type=node_type, note=note)
        nid = await kg.upsert_node(
            tenant_id=tenant_id,
            node_type=node_type,
            canonical_key=canonical,
            properties=properties,
        )
        nodes_added += 1
        return nid

    for doc_id, ex in report.extractions.items():
        cluster = report.clusters.get(doc_id)
        if cluster is None:
            continue

        # Document node — never resolved (each doc is unique).
        doc_node_id = await kg.upsert_node(
            tenant_id=tenant_id,
            node_type="Document",
            canonical_key=str(doc_id),
            properties={
                "doc_type": cluster.doc_type,
                "industry": cluster.industry,
                "vendor": cluster.vendor,
            },
        )
        nodes_added += 1

        # Vendor — resolved against existing vendors.
        vendor_raw = _str_field(ex.fields, "vendor") or cluster.vendor
        vendor_key = normalize_vendor_name(vendor_raw) if vendor_raw else None
        if vendor_key and vendor_key != "unknown":
            vendor_id = await _resolve_and_upsert(
                "Vendor", vendor_key,
                properties={"display_name": vendor_key.title()},
            )
            await kg.upsert_edge(
                tenant_id=tenant_id, src_id=doc_node_id,
                dst_id=vendor_id, edge_type="BILLED_BY",
            )
            edges_added += 1

        # Customer — resolved.
        customer_raw = _str_field(ex.fields, "customer")
        if customer_raw:
            customer_key = normalize_vendor_name(customer_raw)
            cust_id = await _resolve_and_upsert(
                "Customer", customer_key,
                properties={"display_name": customer_raw},
            )
            await kg.upsert_edge(
                tenant_id=tenant_id, src_id=doc_node_id,
                dst_id=cust_id, edge_type="BELONGS_TO_CUSTOMER",
            )
            edges_added += 1

        # Account — resolved (account numbers can vary by leading zero etc).
        account_key = _str_field(ex.fields, "account_number")
        if account_key:
            acc_id = await _resolve_and_upsert(
                "Account", account_key,
                properties={"display_name": f"Account {account_key}"},
            )
            await kg.upsert_edge(
                tenant_id=tenant_id, src_id=doc_node_id, dst_id=acc_id,
                edge_type="INVOICE_FOR" if cluster.doc_type == "invoice" else "REFERENCES",
            )
            edges_added += 1

    # Drop a single audit row summarising the merges for this batch.
    if merge_notes:
        kg.session.add(
            AuditEvent(
                tenant_id=tenant_id,
                actor="graph_builder",
                action="entity_resolution.batch",
                object_type="kg",
                object_id=None,
                payload={"merges": merge_notes},
            )
        )

    isolated = await kg.isolated_nodes()
    return GraphDelta(
        nodes_added=nodes_added,
        edges_added=edges_added,
        merges_proposed=merges_proposed,
        isolated_nodes=len(isolated),
    )
