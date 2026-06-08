"""Streaming chat endpoint — the agent over SSE.

`POST /api/v1/chat` runs one agent turn and streams its progress: a `conversation`
event (the id, so the client can continue the thread), then the loop's
`tool_call` / `tool_result` / `answer` events, then `done`. The user message is
persisted before the turn and the assistant message (with citations + the
tool-call trail) after, so the conversation is durable and resumable.

The SSE generator manages its **own** session via `get_session_factory()` rather
than a request-scoped dependency: the body runs after the endpoint returns the
`EventSourceResponse`, by which point a dependency-yielded session would be
closed. (Same reason apps/api's eval stream uses a raw engine.)
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from promptforge_ragent.agent.loop import run_agent
from promptforge_ragent.agent.tools import ToolContext
from promptforge_ragent.core.db import get_session, get_session_factory
from promptforge_ragent.core.deps import Principal, get_principal
from promptforge_ragent.models import Conversation, Corpus, Message, MessageRole
from promptforge_ragent.services.demo_quota import (
    client_ip,
    free_turns_remaining,
    hmac_ip,
    record_free_turn,
)
from promptforge_ragent.services.system_prompt import get_system_prompt

router = APIRouter(tags=["chat"])

_DEMO_ROLE = "demo"


class ChatRequest(BaseModel):
    message: str
    corpus_id: UUID | None = None
    corpus_slug: str | None = None
    conversation_id: UUID | None = None


def _sse(event: str, payload: dict[str, Any]) -> dict[str, str]:
    return {"event": event, "data": json.dumps(payload)}


async def _resolve_corpus(
    session: AsyncSession, org_id: UUID, corpus_id: UUID | None, slug: str | None
) -> Corpus | None:
    stmt = select(Corpus).where(Corpus.org_id == org_id)
    if corpus_id is not None:
        stmt = stmt.where(Corpus.id == corpus_id)
    elif slug is not None:
        stmt = stmt.where(Corpus.slug == slug)
    else:
        return None
    return (await session.execute(stmt)).scalar_one_or_none()


async def _load_history(session: AsyncSession, conversation_id: UUID) -> list[dict[str, str]]:
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
    return [
        {"role": m.role.value, "content": m.content}
        for m in rows
        if m.role in (MessageRole.USER, MessageRole.ASSISTANT)
    ]


async def _chat_events(
    principal: Principal,
    body: ChatRequest,
    provider_key: str | None,
    free_demo_ip_hmac: str | None,
) -> AsyncIterator[dict[str, str]]:
    if not body.message.strip():
        yield _sse("error", {"error": "message must not be empty"})
        yield _sse("done", {})
        return

    async with get_session_factory()() as session:
        # Resolve the conversation + corpus, scoped to the caller's org.
        if body.conversation_id is not None:
            conversation = await session.get(Conversation, body.conversation_id)
            if conversation is None or conversation.org_id != principal.org_id:
                yield _sse("error", {"error": "conversation not found"})
                yield _sse("done", {})
                return
            corpus = (
                await session.get(Corpus, conversation.corpus_id)
                if conversation.corpus_id
                else None
            )
        else:
            corpus = await _resolve_corpus(
                session, principal.org_id, body.corpus_id, body.corpus_slug
            )
            conversation = None

        if corpus is None:
            yield _sse("error", {"error": "corpus not found"})
            yield _sse("done", {})
            return

        if conversation is None:
            conversation = Conversation(
                org_id=principal.org_id,
                corpus_id=corpus.id,
                user_id=principal.user_id,
                title=body.message.strip()[:80],
            )
            session.add(conversation)
            await session.flush()

        # History is prior turns only — load before persisting this user message.
        history = await _load_history(session, conversation.id)
        session.add(
            Message(
                conversation_id=conversation.id,
                org_id=principal.org_id,
                role=MessageRole.USER,
                content=body.message,
            )
        )
        await session.commit()

        yield _sse("conversation", {"conversation_id": str(conversation.id)})

        system_prompt = await get_system_prompt(session)
        ctx = ToolContext(session=session, corpus=corpus)
        tool_trail: list[dict[str, Any]] = []
        answer: dict[str, Any] | None = None

        async for event in run_agent(
            ctx,
            system_prompt=system_prompt,
            history=history,
            user_message=body.message,
            api_key=provider_key,
        ):
            if event["type"] == "tool_call":
                tool_trail.append({"tool": event["tool"], "arguments": event["arguments"]})
            if event["type"] == "answer":
                answer = event
            yield _sse(event["type"], event)

        if answer is not None:
            session.add(
                Message(
                    conversation_id=conversation.id,
                    org_id=principal.org_id,
                    role=MessageRole.ASSISTANT,
                    content=answer.get("content", ""),
                    citations=answer.get("citations") or None,
                    tool_calls=tool_trail or None,
                )
            )
            # Count a free demo turn only when one actually produced an answer.
            if free_demo_ip_hmac is not None:
                await record_free_turn(session, free_demo_ip_hmac)
            await session.commit()

        yield _sse("done", {})


@router.post("/chat")
async def chat(
    body: ChatRequest,
    request: Request,
    principal: Principal = Depends(get_principal),
    x_provider_key: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> EventSourceResponse:
    """Run one agent turn over the corpus and stream the result as SSE.

    Demo visitors run on the hosted key only while free turns remain (per-IP +
    global daily caps); once exhausted they must BYOK (`X-Provider-Key`) or get a
    402. Owners/members always use the hosted key. The 402 is raised here, before
    streaming starts — once the SSE response is open the status is already 200.
    """
    free_demo_ip_hmac: str | None = None
    if principal.role == _DEMO_ROLE and not x_provider_key:
        ip_hmac = hmac_ip(client_ip(request))
        if await free_turns_remaining(session, ip_hmac) <= 0:
            raise HTTPException(
                status.HTTP_402_PAYMENT_REQUIRED,
                "free demo turns exhausted — add an X-Provider-Key header to continue",
            )
        free_demo_ip_hmac = ip_hmac  # record the turn once it produces an answer

    return EventSourceResponse(_chat_events(principal, body, x_provider_key, free_demo_ip_hmac))
