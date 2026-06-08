"""E2E: POST /api/v1/chat streams the agent and persists the turn.

Drives the full HTTP stack — auth, corpus resolution, the agent loop over the
REAL tools, SSE streaming, and Conversation/Message persistence — with only
litellm + the query embedding mocked. The SSE response is finite so a plain
awaited POST returns the whole body in `resp.text` (same approach apps/api uses
for its eval-stream e2e).
"""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from promptforge_ragent.agent import loop as loop_module
from promptforge_ragent.models import (
    Chunk,
    Corpus,
    Document,
    DocumentStatus,
    EmbeddingModel,
    Message,
    MessageRole,
)
from promptforge_ragent.services import retrieval

pytestmark = pytest.mark.e2e

_SECRET = "a" * 48
_NEAR = [1.0] + [0.0] * 1535


def _token(user_id: UUID, org_id: UUID) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "org": str(org_id),
        "role": "member",
        "typ": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=15)).timestamp()),
    }
    return jwt.encode(payload, _SECRET, algorithm="HS256")


def _parse_sse(text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    text = text.replace("\r\n", "\n")  # sse-starlette uses CRLF separators
    for block in text.strip().split("\n\n"):
        event = None
        data = None
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data = line[len("data:") :].strip()
        if event is not None:
            events.append({"event": event, "data": json.loads(data) if data else {}})
    return events


async def _seed(factory: async_sessionmaker[AsyncSession]) -> tuple[UUID, UUID, UUID]:
    async with factory() as session:
        org_id, user_id = uuid4(), uuid4()
        await session.execute(Corpus.metadata.tables["orgs"].insert().values(id=org_id))
        await session.execute(Corpus.metadata.tables["users"].insert().values(id=user_id))
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
        chunk_id = chunk.id
        await session.commit()
    return org_id, user_id, chunk_id


async def test_chat_streams_and_persists(
    app_client: AsyncClient,
    committed_db: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id, user_id, chunk_id = await _seed(committed_db)

    async def fake_embed(model: object, texts: list[str], **kwargs: object) -> list[list[float]]:
        return [_NEAR]

    monkeypatch.setattr(retrieval, "embed_texts", fake_embed)

    responses = iter(
        [
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=None,
                            tool_calls=[
                                SimpleNamespace(
                                    id="c1",
                                    function=SimpleNamespace(
                                        name="search_docs", arguments='{"query": "quick fox"}'
                                    ),
                                )
                            ],
                        )
                    )
                ]
            ),
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=None,
                            tool_calls=[
                                SimpleNamespace(
                                    id="c2",
                                    function=SimpleNamespace(
                                        name="cite_sources",
                                        arguments=f'{{"chunk_ids": ["{chunk_id}"]}}',
                                    ),
                                )
                            ],
                        )
                    )
                ]
            ),
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="A quick fox.", tool_calls=None)
                    )
                ]
            ),
        ]
    )

    async def fake_acompletion(**kwargs: Any) -> SimpleNamespace:
        return next(responses)

    monkeypatch.setattr(loop_module.litellm, "acompletion", fake_acompletion)

    resp = await app_client.post(
        "/api/v1/chat",
        json={"message": "quick fox", "corpus_slug": "docs"},
        headers={"Authorization": f"Bearer {_token(user_id, org_id)}"},
    )

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    events = _parse_sse(resp.text)
    kinds = [e["event"] for e in events]
    assert kinds[0] == "conversation"
    assert "tool_call" in kinds
    assert "answer" in kinds
    assert kinds[-1] == "done"

    answer = next(e["data"] for e in events if e["event"] == "answer")
    assert answer["content"] == "A quick fox."
    assert answer["citations"][0]["chunk_id"] == str(chunk_id)

    conversation_id = UUID(
        next(e["data"]["conversation_id"] for e in events if e["event"] == "conversation")
    )

    # User + assistant messages persisted; assistant carries citations + tool trail.
    async with committed_db() as session:
        rows = (
            (
                await session.execute(
                    select(Message)
                    .where(Message.conversation_id == conversation_id)
                    .order_by(Message.created_at)
                )
            )
            .scalars()
            .all()
        )
    assert [m.role for m in rows] == [MessageRole.USER, MessageRole.ASSISTANT]
    assistant = rows[1]
    assert assistant.content == "A quick fox."
    assert assistant.citations[0]["chunk_id"] == str(chunk_id)
    assert assistant.tool_calls[0]["tool"] == "search_docs"


async def test_chat_requires_auth(app_client: AsyncClient) -> None:
    resp = await app_client.post("/api/v1/chat", json={"message": "hi", "corpus_slug": "docs"})
    assert resp.status_code == 401


async def test_chat_unknown_corpus_streams_error(
    app_client: AsyncClient,
    committed_db: async_sessionmaker[AsyncSession],
) -> None:
    org_id, user_id = uuid4(), uuid4()
    async with committed_db() as session:
        from sqlalchemy import text

        await session.execute(text("INSERT INTO orgs (id) VALUES (:id)"), {"id": org_id})
        await session.commit()

    resp = await app_client.post(
        "/api/v1/chat",
        json={"message": "hi", "corpus_slug": "nope"},
        headers={"Authorization": f"Bearer {_token(user_id, org_id)}"},
    )
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    assert any(e["event"] == "error" for e in events)
