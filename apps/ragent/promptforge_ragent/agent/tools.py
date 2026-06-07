"""The agent's three tools, as litellm function-calling schemas + handlers.

ReAct gives the model a small, transparent toolset it drives one call at a time:
- `search_docs`   — hybrid retrieval (+ optional rerank) → ranked snippets + ids
- `fetch_passage` — full text of one chunk (search snippets are truncated)
- `cite_sources`  — declare which chunks the answer rests on (→ message citations)

Handlers are bound to a `ToolContext` (the conversation's corpus + a DB session)
and every read is scoped to that corpus + its org. They return JSON-serializable
dicts and, crucially, return an `{"error": ...}` dict instead of raising on bad
arguments or missing rows — the ReAct loop feeds that back to the model so it can
self-correct, which a raised exception would prevent.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from promptforge_ragent.models import Chunk, Corpus, Document
from promptforge_ragent.services.rerank import rerank
from promptforge_ragent.services.retrieval import hybrid_search

_SNIPPET_LIMIT = 280
_CANDIDATE_POOL = 20  # hybrid candidates fetched before rerank narrows to top_k


@dataclass
class ToolContext:
    session: AsyncSession
    corpus: Corpus


# OpenAI / litellm function-calling schemas. Kept terse but explicit so the model
# knows chunk_ids come from search_docs and that cite_sources precedes the answer.
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_docs",
            "description": (
                "Search the knowledge base for passages relevant to a query. "
                "Returns ranked snippets, each with a chunk_id and its document title."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search for."},
                    "top_k": {
                        "type": "integer",
                        "description": "Maximum results to return (default 5).",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_passage",
            "description": (
                "Fetch the full text of a chunk by its chunk_id. Use when a "
                "search_docs snippet is truncated and you need the complete passage."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "chunk_id": {"type": "string", "description": "A chunk_id from search_docs."},
                },
                "required": ["chunk_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cite_sources",
            "description": (
                "Declare the chunks your answer is based on. Call this with the "
                "chunk_ids you used right before giving the final answer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "chunk_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "chunk_ids that support the answer.",
                    },
                },
                "required": ["chunk_ids"],
            },
        },
    },
]


def _snippet(text: str, limit: int = _SNIPPET_LIMIT) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _parse_uuid(value: object) -> UUID | None:
    try:
        return UUID(str(value))
    except (ValueError, TypeError):
        return None


async def _document_titles(session: AsyncSession, doc_ids: set[UUID]) -> dict[UUID, str]:
    if not doc_ids:
        return {}
    rows = (
        await session.execute(select(Document.id, Document.title).where(Document.id.in_(doc_ids)))
    ).all()
    return {row[0]: row[1] for row in rows}


async def _search_docs(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        return {"error": "query is required and must be a non-empty string"}
    top_k = args.get("top_k", 5)
    top_k = top_k if isinstance(top_k, int) and top_k > 0 else 5

    candidates = await hybrid_search(ctx.session, ctx.corpus, query, top_n=_CANDIDATE_POOL)
    results = await rerank(query, candidates, top_n=top_k)
    titles = await _document_titles(ctx.session, {r.document_id for r in results})
    return {
        "results": [
            {
                "chunk_id": str(r.chunk_id),
                "document_title": titles.get(r.document_id, ""),
                "ordinal": r.ordinal,
                "snippet": _snippet(r.content),
                "score": round(r.score, 4),
            }
            for r in results
        ]
    }


async def _fetch_passage(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    chunk_id = _parse_uuid(args.get("chunk_id"))
    if chunk_id is None:
        return {"error": "a valid chunk_id is required"}
    chunk = await ctx.session.get(Chunk, chunk_id)
    if chunk is None or chunk.corpus_id != ctx.corpus.id or chunk.org_id != ctx.corpus.org_id:
        return {"error": "chunk not found in this corpus"}
    titles = await _document_titles(ctx.session, {chunk.document_id})
    return {
        "chunk_id": str(chunk.id),
        "document_title": titles.get(chunk.document_id, ""),
        "ordinal": chunk.ordinal,
        "content": chunk.content,
    }


async def _cite_sources(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    raw_ids = args.get("chunk_ids")
    if not isinstance(raw_ids, list) or not raw_ids:
        return {"error": "chunk_ids must be a non-empty list"}
    wanted = [cid for cid in (_parse_uuid(v) for v in raw_ids) if cid is not None]
    if not wanted:
        return {"error": "no valid chunk_ids provided"}

    rows = (
        (
            await ctx.session.execute(
                select(Chunk).where(
                    Chunk.id.in_(wanted),
                    Chunk.corpus_id == ctx.corpus.id,
                    Chunk.org_id == ctx.corpus.org_id,
                )
            )
        )
        .scalars()
        .all()
    )
    titles = await _document_titles(ctx.session, {c.document_id for c in rows})
    # Preserve the model's requested order, dropping ids not in this corpus.
    by_id = {c.id: c for c in rows}
    citations = [
        {
            "chunk_id": str(c.id),
            "document_title": titles.get(c.document_id, ""),
            "ordinal": c.ordinal,
            "snippet": _snippet(c.content),
        }
        for cid in wanted
        if (c := by_id.get(cid)) is not None
    ]
    return {"citations": citations}


_HANDLERS: dict[str, Callable[[ToolContext, dict[str, Any]], Awaitable[dict[str, Any]]]] = {
    "search_docs": _search_docs,
    "fetch_passage": _fetch_passage,
    "cite_sources": _cite_sources,
}


async def execute_tool(name: str, arguments: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """Dispatch a tool call to its handler. Unknown tool → error dict (not a raise)."""
    handler = _HANDLERS.get(name)
    if handler is None:
        return {"error": f"unknown tool: {name}"}
    return await handler(ctx, arguments)
