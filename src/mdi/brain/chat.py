"""Chat — supporting layer.

Routing:
  * Relationship questions ("vendors for tenant X", "documents for account Y") go through
    the knowledge graph — sub-100ms, no LLM.
  * Synthesis questions ("summarize Q1 spend trend") go to Gemini Pro with the relevant
    extractions + briefings as context.
  * Hybrid: the router pre-fetches graph evidence, then asks the LLM to narrate.
"""
from __future__ import annotations

import re
import time
from typing import Any
from uuid import UUID

from mdi.brain.knowledge_graph import KnowledgeGraph
from mdi.kernel.llm_gateway import GatewayLike, get_gateway
from mdi.models.schemas import ChatRequest, ChatResponse


# Light-weight intent router. Production would ship a small classifier.
_RELATIONSHIP_PATTERNS = (
    re.compile(r"\b(list|show|all)\s+(vendors|customers|accounts|documents)\b", re.I),
    re.compile(r"\bdocuments?\s+(for|of)\s+(account|customer|vendor)\b", re.I),
    re.compile(r"\bwho\s+billed\b", re.I),
)


def _route(question: str) -> str:
    if any(p.search(question) for p in _RELATIONSHIP_PATTERNS):
        return "graph"
    return "hybrid"


async def _graph_answer(kg: KnowledgeGraph, question: str) -> tuple[str, list[UUID]]:
    q = question.lower()
    if "vendor" in q:
        rows = await kg.find_nodes(node_type="Vendor", limit=200)
    elif "customer" in q:
        rows = await kg.find_nodes(node_type="Customer", limit=200)
    elif "account" in q:
        rows = await kg.find_nodes(node_type="Account", limit=200)
    elif "document" in q:
        rows = await kg.find_nodes(node_type="Document", limit=200)
    else:
        rows = []
    if not rows:
        return "No matching entities found in the knowledge graph.", []
    bullet = "\n".join(
        f"  - {r['canonical_key']}" for r in rows[:50]
    )
    return f"Found {len(rows)} entries:\n{bullet}", [r["id"] for r in rows[:20] if isinstance(r["id"], UUID)]


async def chat(
    *,
    kg: KnowledgeGraph,
    request: ChatRequest,
    gateway: GatewayLike | None = None,
) -> ChatResponse:
    started = time.monotonic()
    route = _route(request.question)

    if route == "graph":
        answer, citations = await _graph_answer(kg, request.question)
        return ChatResponse(
            answer=answer,
            route="graph",
            citations=citations,
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )

    # Hybrid: gather graph context + RAG chunks, then ask the LLM to synthesise.
    gw = gateway or get_gateway()

    centrality = await kg.degree_centrality(top_n=10)
    graph_block = "TOP ENTITIES BY DEGREE:\n" + "\n".join(
        f"  - {row['node_type']}: {row['canonical_key']} (degree={row['degree']})"
        for row in centrality
    )

    # RAG retrieval — fetch top-K relevant doc chunks for grounded synthesis.
    rag_block = ""
    citations: list[UUID] = []
    try:
        from mdi.brain.rag import RAGRetriever, format_for_prompt
        retriever = RAGRetriever(use_real_embeddings=False)
        chunks = await retriever.retrieve(kg.session, query=request.question, top_k=6)
        rag_block = format_for_prompt(chunks)
        citations = [c.document_id for c in chunks]
    except Exception:  # noqa: BLE001
        rag_block = ""

    system = (
        "You are an analyst chatbot grounded in a knowledge graph and retrieved document chunks. "
        "Cite which chunk(s) you used when relevant. If the provided context doesn't answer the question, say so."
    )
    history_block = "\n".join(
        f"{turn.role.upper()}: {turn.content}" for turn in request.history
    )
    prompt_parts = [graph_block]
    if rag_block:
        prompt_parts.append(rag_block)
    if history_block:
        prompt_parts.append(history_block)
    prompt_parts.append(f"USER: {request.question}\nASSISTANT:")
    prompt = "\n\n".join(prompt_parts)

    try:
        resp = await gw.generate(
            organ="chat",
            tier="synthesis",
            system=system,
            prompt=prompt,
            json_mode=False,
            max_output_tokens=1024,
            temperature=0.2,
        )
        answer = resp.text.strip()
    except Exception:  # noqa: BLE001
        answer = "Could not reach the LLM. Try a relationship question — those are graph-routed."

    return ChatResponse(
        answer=answer,
        route="hybrid",
        citations=citations,
        elapsed_ms=int((time.monotonic() - started) * 1000),
    )
