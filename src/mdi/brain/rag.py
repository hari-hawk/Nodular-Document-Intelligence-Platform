"""RAG sidecar — document-chunk retrieval for the Chat layer.

Why it exists
-------------
Pattern memory (Hippocampus) retrieves *patterns* — schema + rules for a
given (industry, vendor, doc_type). That's the right grain for the pipeline.
For Chat synthesis ("what are the renewal terms across my contracts?") we
need *document content*, not schemas. This module chunks ingested docs,
embeds the chunks, stores them in `doc_chunks`, and retrieves top-K matches
for an arbitrary question.

Design notes
------------
- Chunk size: ~512 tokens (≈ 2KB) with a 64-token overlap. Picked to keep
  retrieval blocks coherent without truncating mid-sentence.
- Embedding model: shared with Hippocampus (BAAI/bge-m3 in production,
  deterministic stub in tests). Same 1024-dim vector space, same pgvector
  HNSW index pattern.
- Idempotency: re-ingesting the same document re-chunks; we don't dedupe
  because document content can be revised. Old chunks rely on the
  `documents` row's cascade-delete.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from mdi.brain.hippocampus import _Embedder
from mdi.kernel.observability import get_logger
from mdi.models.db import DocChunk

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Chunker — naïve sentence-window splitter with a stride.
# ---------------------------------------------------------------------------
_SENT_RE = re.compile(r"(?<=[.!?])\s+|\n{2,}")


def _approx_tokens(s: str) -> int:
    """1 token ≈ 4 chars for English. Good enough for chunk sizing."""
    return max(1, len(s) // 4)


def chunk_text(text_in: str, *, target_tokens: int = 512, overlap_tokens: int = 64) -> list[str]:
    """Split text into ~target_tokens chunks with overlap.

    Uses sentence boundaries when possible, falls back to fixed-width slicing
    if the input has none (e.g. a CSV).
    """
    text_in = (text_in or "").strip()
    if not text_in:
        return []

    sentences = [s.strip() for s in _SENT_RE.split(text_in) if s.strip()]
    if not sentences:
        # No detectable sentences — slice by character window.
        approx_char_window = target_tokens * 4
        return [
            text_in[i : i + approx_char_window]
            for i in range(0, len(text_in), max(approx_char_window - overlap_tokens * 4, 1))
        ]

    chunks: list[str] = []
    cur: list[str] = []
    cur_tokens = 0
    for sent in sentences:
        st = _approx_tokens(sent)
        if cur and cur_tokens + st > target_tokens:
            chunks.append(" ".join(cur))
            # Overlap: rewind a few sentences from the tail.
            overlap_chunk: list[str] = []
            overlap_count = 0
            for s in reversed(cur):
                if overlap_count >= overlap_tokens:
                    break
                overlap_chunk.insert(0, s)
                overlap_count += _approx_tokens(s)
            cur = overlap_chunk
            cur_tokens = overlap_count
        cur.append(sent)
        cur_tokens += st

    if cur:
        chunks.append(" ".join(cur))
    return chunks


# ---------------------------------------------------------------------------
# Index — write embeddings for a document.
# ---------------------------------------------------------------------------
@dataclass
class RAGIndex:
    # None defers to settings.use_real_embeddings — same default as Hippocampus.
    use_real_embeddings: bool | None = None

    def __post_init__(self) -> None:
        self.embedder = _Embedder(use_real_model=self.use_real_embeddings)

    async def index_document(
        self,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        document_id: uuid.UUID,
        document_text: str,
    ) -> int:
        """Chunk + embed + upsert. Returns the number of chunks written."""
        chunks = chunk_text(document_text)
        if not chunks:
            return 0

        rows = []
        for idx, chunk in enumerate(chunks):
            emb = self.embedder.embed(chunk)
            rows.append({
                "tenant_id": tenant_id,
                "document_id": document_id,
                "chunk_idx": idx,
                "text": chunk,
                "token_count": _approx_tokens(chunk),
                "embedding": emb,
            })

        for row in rows:
            stmt = (
                pg_insert(DocChunk.__table__)
                .values(**row)
                .on_conflict_do_update(
                    constraint="uq_doc_chunk_idx",
                    set_={
                        "text": row["text"],
                        "token_count": row["token_count"],
                        "embedding": row["embedding"],
                    },
                )
            )
            await db.execute(stmt)

        logger.info("rag.indexed", document_id=str(document_id), chunks=len(rows))
        return len(rows)


# ---------------------------------------------------------------------------
# Retriever — top-K cosine matches.
# ---------------------------------------------------------------------------
@dataclass
class Retrieved:
    document_id: uuid.UUID
    chunk_idx: int
    text: str
    similarity: float


class RAGRetriever:
    def __init__(self, *, use_real_embeddings: bool | None = None) -> None:
        # None defers to settings.use_real_embeddings — same default as
        # RAGIndex and Hippocampus.
        self.embedder = _Embedder(use_real_model=use_real_embeddings)

    async def retrieve(
        self,
        db: AsyncSession,
        *,
        query: str,
        top_k: int = 6,
        min_similarity: float = 0.20,
    ) -> list[Retrieved]:
        emb = self.embedder.embed(query)
        emb_literal = "[" + ",".join(format(x, ".7f") for x in emb) + "]"
        rows = (
            await db.execute(
                text(
                    """
                    SELECT document_id::text AS doc_id, chunk_idx, text,
                           1 - (embedding <=> CAST(:vec AS vector)) AS sim
                    FROM doc_chunks
                    WHERE embedding IS NOT NULL
                    ORDER BY embedding <=> CAST(:vec AS vector)
                    LIMIT :k
                    """
                ),
                {"vec": emb_literal, "k": top_k},
            )
        ).all()
        out: list[Retrieved] = []
        for r in rows:
            if float(r.sim) < min_similarity:
                continue
            out.append(
                Retrieved(
                    document_id=uuid.UUID(r.doc_id),
                    chunk_idx=int(r.chunk_idx),
                    text=str(r.text),
                    similarity=float(r.sim),
                )
            )
        return out


def format_for_prompt(chunks: list[Retrieved], *, max_chars: int = 6000) -> str:
    """Render retrieved chunks as a prompt context block."""
    if not chunks:
        return ""
    parts: list[str] = ["RETRIEVED DOCUMENT CHUNKS (use these as primary evidence):"]
    used = 0
    for i, c in enumerate(chunks):
        body = c.text.strip()
        snippet = f"\n--- chunk {i+1} · doc {str(c.document_id)[:8]} · sim={c.similarity:.2f} ---\n{body}"
        if used + len(snippet) > max_chars:
            parts.append("\n(further chunks truncated for prompt budget)")
            break
        parts.append(snippet)
        used += len(snippet)
    return "\n".join(parts)
