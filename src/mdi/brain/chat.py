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
    except Exception:
        rag_block = ""

    # System prompt — tuned for the "brisk analyst + decline-and-suggest"
    # persona chosen during product review. The shape matters:
    #
    #   * Style first (numbers-first, 1-3 sentences, no filler) — sets
    #     length expectations BEFORE the model sees the context, so it
    #     doesn't pad answers to fill space.
    #   * Citation rule second — frames citations as a requirement, not
    #     an optional embellishment, so we get them consistently.
    #   * Out-of-scope rule third — explicit "decline + suggest one
    #     related answerable question" pattern prevents both hallucination
    #     AND the dead-end feeling of a bare "I don't know."
    #   * Formatting rules last — currency / date / units constraints
    #     keep output machine-parseable for downstream chips/tables in
    #     the UI without per-call formatting prompts.
    system = (
        "You are MDI Brain — a brisk analyst chatbot grounded in a tenant's "
        "knowledge graph and retrieved document chunks.\n\n"
        "Style: numbers-first, 1–3 sentences. Lead with the answer, then a brief "
        "reason. No filler phrases (\"great question\", \"let me check\"), no "
        "hedging where the data is clear.\n\n"
        "Citations: when the answer relies on retrieved chunks, name the chunks "
        "you used. If multiple contributed, cite the most authoritative one.\n\n"
        "Out-of-scope behaviour: if the provided context doesn't answer the "
        "question, say so plainly — \"I don't have that in your indexed "
        "documents\" — and IMMEDIATELY suggest one related question you CAN "
        "answer from the visible context (e.g. \"but I can tell you the top "
        "5 vendors by spend if useful\"). Never guess; never use general world "
        "knowledge unless the user explicitly asks for it.\n\n"
        "Formatting: currency with symbol and 2 decimals (e.g. $12,450.00). "
        "Dates as YYYY-MM-DD. Always include units."
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
    except Exception:
        answer = "Could not reach the LLM. Try a relationship question — those are graph-routed."

    return ChatResponse(
        answer=answer,
        route="hybrid",
        citations=citations,
        elapsed_ms=int((time.monotonic() - started) * 1000),
    )
