"""Knowledge Graph — Postgres-backed adjacency list with a NetworkX-compatible API.

Survives concurrent writes via row-level uniqueness constraints + ON
CONFLICT upserts. RLS isolates tenants automatically: every query runs
inside a `tenant_session` so policies fire.
"""
from __future__ import annotations

import uuid
from typing import Any, Iterable

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from mdi.models.db import KGEdge, KGNode
from mdi.models.schemas import EdgeType, NodeType


class KnowledgeGraph:
    """All operations are tenant-scoped via the session's RLS context."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Mutations — idempotent upserts
    # ------------------------------------------------------------------
    async def upsert_node(
        self,
        *,
        tenant_id: uuid.UUID,
        node_type: NodeType,
        canonical_key: str,
        properties: dict[str, Any] | None = None,
        aliases: list[str] | None = None,
        confidence: float = 1.0,
    ) -> uuid.UUID:
        stmt = (
            pg_insert(KGNode.__table__)
            .values(
                tenant_id=tenant_id,
                node_type=node_type,
                canonical_key=canonical_key,
                properties=properties or {},
                aliases=aliases or [],
                confidence=confidence,
            )
            .on_conflict_do_update(
                constraint="uq_kg_node_scope",
                set_={
                    "properties": (properties or {}),
                    "aliases": (aliases or []),
                    "confidence": confidence,
                },
            )
            .returning(KGNode.__table__.c.id)
        )
        row = (await self.session.execute(stmt)).first()
        assert row is not None
        return row.id  # type: ignore[no-any-return]

    async def upsert_edge(
        self,
        *,
        tenant_id: uuid.UUID,
        src_id: uuid.UUID,
        dst_id: uuid.UUID,
        edge_type: EdgeType,
        properties: dict[str, Any] | None = None,
        confidence: float = 1.0,
    ) -> None:
        stmt = (
            pg_insert(KGEdge.__table__)
            .values(
                tenant_id=tenant_id,
                src_id=src_id,
                dst_id=dst_id,
                edge_type=edge_type,
                properties=properties or {},
                confidence=confidence,
            )
            .on_conflict_do_update(
                constraint="uq_kg_edge_scope",
                set_={
                    "properties": (properties or {}),
                    "confidence": confidence,
                },
            )
        )
        await self.session.execute(stmt)

    # ------------------------------------------------------------------
    # Queries — NetworkX-compatible enough for chat/insights
    # ------------------------------------------------------------------
    async def neighbors(
        self,
        node_id: uuid.UUID,
        *,
        edge_types: Iterable[EdgeType] | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"node_id": node_id}
        where_extra = ""
        if edge_types:
            params["edge_types"] = list(edge_types)
            where_extra = " AND e.edge_type = ANY(:edge_types)"
        rows = (
            await self.session.execute(
                text(
                    f"""
                    SELECT n.id, n.node_type, n.canonical_key, n.properties, e.edge_type
                    FROM kg_edges e
                    JOIN kg_nodes n
                      ON n.id = CASE WHEN e.src_id = :node_id THEN e.dst_id ELSE e.src_id END
                    WHERE (e.src_id = :node_id OR e.dst_id = :node_id)
                          {where_extra}
                    """
                ),
                params,
            )
        ).all()
        return [
            {
                "id": r.id,
                "node_type": r.node_type,
                "canonical_key": r.canonical_key,
                "properties": r.properties,
                "edge_type": r.edge_type,
            }
            for r in rows
        ]

    async def find_nodes(
        self,
        *,
        node_type: NodeType | None = None,
        key_like: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        stmt = select(KGNode).limit(limit)
        if node_type is not None:
            stmt = stmt.where(KGNode.node_type == node_type)
        if key_like is not None:
            stmt = stmt.where(KGNode.canonical_key.ilike(f"%{key_like}%"))
        rows = (await self.session.execute(stmt)).scalars().all()
        return [
            {
                "id": r.id,
                "node_type": r.node_type,
                "canonical_key": r.canonical_key,
                "properties": r.properties,
                "aliases": r.aliases,
                "confidence": r.confidence,
            }
            for r in rows
        ]

    async def degree_centrality(self, top_n: int = 10) -> list[dict[str, Any]]:
        rows = (
            await self.session.execute(
                text(
                    """
                    SELECT n.id, n.node_type, n.canonical_key,
                           COUNT(e.id) AS degree
                    FROM kg_nodes n
                    LEFT JOIN kg_edges e
                      ON e.src_id = n.id OR e.dst_id = n.id
                    GROUP BY n.id, n.node_type, n.canonical_key
                    ORDER BY degree DESC
                    LIMIT :top_n
                    """
                ),
                {"top_n": top_n},
            )
        ).all()
        return [
            {
                "id": r.id,
                "node_type": r.node_type,
                "canonical_key": r.canonical_key,
                "degree": int(r.degree),
            }
            for r in rows
        ]

    async def merge_nodes(
        self,
        *,
        tenant_id: uuid.UUID,
        node_type: NodeType,
        source_canonical_key: str,
        target_canonical_key: str,
    ) -> dict[str, Any]:
        """Merge `source` into `target`.

        Steps (under one transaction):
          1. Look up both node IDs.
          2. Re-point every edge whose src_id or dst_id == source.id to target.id.
             ON CONFLICT (uq_kg_edge_scope) — drop the duplicate if the
             merge would create a duplicate edge.
          3. Append source.canonical_key (and source.aliases) into target.aliases.
          4. Delete source.

        Returns a summary dict with the counts.
        """
        # Find both nodes.
        rows = (
            await self.session.execute(
                text(
                    "SELECT id, canonical_key, aliases FROM kg_nodes "
                    "WHERE node_type = :nt "
                    "  AND canonical_key IN (:s, :t)"
                ),
                {"nt": node_type, "s": source_canonical_key, "t": target_canonical_key},
            )
        ).all()
        by_key = {r.canonical_key: r for r in rows}
        if source_canonical_key not in by_key:
            return {"merged": False, "reason": "source node not found"}
        if target_canonical_key not in by_key:
            return {"merged": False, "reason": "target node not found"}
        source = by_key[source_canonical_key]
        target = by_key[target_canonical_key]

        # SELECT FOR UPDATE on both nodes — minimal contention guard.
        await self.session.execute(
            text("SELECT id FROM kg_nodes WHERE id IN (:s, :t) FOR UPDATE"),
            {"s": source.id, "t": target.id},
        )

        # Re-point edges where source is the src. We dedupe via ON CONFLICT.
        await self.session.execute(
            text(
                "WITH moved AS ("
                "  UPDATE kg_edges SET src_id = :tgt "
                "  WHERE src_id = :src "
                "  RETURNING id"
                ") SELECT COUNT(*) FROM moved"
            ),
            {"tgt": target.id, "src": source.id},
        )
        # Same for dst direction.
        await self.session.execute(
            text(
                "WITH moved AS ("
                "  UPDATE kg_edges SET dst_id = :tgt "
                "  WHERE dst_id = :src "
                "  RETURNING id"
                ") SELECT COUNT(*) FROM moved"
            ),
            {"tgt": target.id, "src": source.id},
        )
        # Clean up self-loops or duplicates created by the re-point.
        await self.session.execute(
            text(
                "DELETE FROM kg_edges a USING kg_edges b "
                "WHERE a.id > b.id "
                "  AND a.src_id = b.src_id AND a.dst_id = b.dst_id "
                "  AND a.edge_type = b.edge_type AND a.tenant_id = b.tenant_id"
            )
        )
        await self.session.execute(
            text("DELETE FROM kg_edges WHERE src_id = dst_id")
        )

        # Append source.canonical_key (and its aliases) to target.aliases.
        merged_aliases = list(target.aliases or [])
        if source.canonical_key not in merged_aliases:
            merged_aliases.append(source.canonical_key)
        for a in (source.aliases or []):
            if a not in merged_aliases:
                merged_aliases.append(a)
        await self.session.execute(
            text("UPDATE kg_nodes SET aliases = :al WHERE id = :id"),
            {"al": merged_aliases, "id": target.id},
        )

        # Delete the source node (cascade kills remaining edges; should be none).
        await self.session.execute(
            text("DELETE FROM kg_nodes WHERE id = :id"),
            {"id": source.id},
        )

        return {
            "merged": True,
            "target_id": str(target.id),
            "source_id": str(source.id),
            "aliases_count": len(merged_aliases),
        }

    async def isolated_nodes(self) -> list[dict[str, Any]]:
        rows = (
            await self.session.execute(
                text(
                    """
                    SELECT n.id, n.node_type, n.canonical_key
                    FROM kg_nodes n
                    LEFT JOIN kg_edges e
                      ON e.src_id = n.id OR e.dst_id = n.id
                    WHERE e.id IS NULL
                    """
                )
            )
        ).all()
        return [
            {"id": r.id, "node_type": r.node_type, "canonical_key": r.canonical_key}
            for r in rows
        ]
