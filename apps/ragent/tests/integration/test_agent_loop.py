"""Integration: the loop drives the REAL tools against Postgres (only litellm mocked).

Proves the chain loop → execute_tool → hybrid_search/cite_sources → real chunks,
with the final answer's citations coming from actual rows.
"""

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from promptforge_ragent.agent import loop as loop_module
from promptforge_ragent.agent.loop import run_agent
from promptforge_ragent.agent.tools import ToolContext
from promptforge_ragent.core.config import get_settings
from promptforge_ragent.models import Chunk, Corpus, Document, DocumentStatus, EmbeddingModel
from promptforge_ragent.services import retrieval

pytestmark = pytest.mark.integration

_NEAR = [1.0] + [0.0] * 1535


def _tool_resp(calls: list[tuple[str, str, str]]) -> SimpleNamespace:
    tcs = [
        SimpleNamespace(id=cid, function=SimpleNamespace(name=name, arguments=args))
        for cid, name, args in calls
    ]
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=tcs))]
    )


def _text_resp(text_content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text_content, tool_calls=None))]
    )


async def _seed(session: AsyncSession) -> tuple[Corpus, Chunk]:
    org_id = uuid4()
    await session.execute(text("INSERT INTO orgs (id) VALUES (:id)"), {"id": org_id})
    corpus = Corpus(
        org_id=org_id, slug="docs", name="Docs", embedding_model=EmbeddingModel.OPENAI_3_SMALL
    )
    session.add(corpus)
    await session.flush()
    doc = Document(
        corpus_id=corpus.id,
        org_id=org_id,
        title="Handbook",
        status=DocumentStatus.READY,
        byte_size=1,
    )
    session.add(doc)
    await session.flush()
    chunk = Chunk(
        document_id=doc.id,
        corpus_id=corpus.id,
        org_id=org_id,
        ordinal=0,
        content="the quick brown fox",
        embedding_1536=_NEAR,
    )
    session.add(chunk)
    await session.flush()
    return corpus, chunk


async def test_loop_with_real_tools_produces_real_citations(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PF_DATABASE_URL", "postgresql+asyncpg://t:t@localhost/t")
    monkeypatch.setenv("PF_JWT_SECRET", "a" * 48)
    get_settings.cache_clear()

    corpus, chunk = await _seed(db_session)

    async def fake_embed(model: object, texts: list[str]) -> list[list[float]]:
        return [_NEAR]

    monkeypatch.setattr(retrieval, "embed_texts", fake_embed)

    # Model: search, then cite the real chunk, then answer.
    responses = iter(
        [
            _tool_resp([("c1", "search_docs", '{"query": "quick fox"}')]),
            _tool_resp([("c2", "cite_sources", f'{{"chunk_ids": ["{chunk.id}"]}}')]),
            _text_resp("The fox is quick and brown."),
        ]
    )

    async def fake_acompletion(**kwargs: Any) -> SimpleNamespace:
        return next(responses)

    monkeypatch.setattr(loop_module.litellm, "acompletion", fake_acompletion)

    ctx = ToolContext(session=db_session, corpus=corpus)
    events = [
        e async for e in run_agent(ctx, system_prompt="sys", history=[], user_message="quick fox")
    ]

    answer = events[-1]
    assert answer["type"] == "answer"
    assert answer["content"] == "The fox is quick and brown."
    assert answer["citations"] == [
        {
            "chunk_id": str(chunk.id),
            "document_title": "Handbook",
            "ordinal": 0,
            "snippet": "the quick brown fox",
        }
    ]
    # The search tool actually returned the seeded chunk.
    search_result = next(
        e for e in events if e["type"] == "tool_result" and e["tool"] == "search_docs"
    )
    assert search_result["ok"]
