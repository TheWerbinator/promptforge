"""Unit: the ReAct loop control flow (litellm + execute_tool mocked)."""

from types import SimpleNamespace
from typing import Any

import pytest

from promptforge_ragent.agent import loop as loop_module
from promptforge_ragent.agent.loop import run_agent
from promptforge_ragent.core.config import get_settings


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PF_DATABASE_URL", "postgresql+asyncpg://t:t@localhost/t")
    monkeypatch.setenv("PF_JWT_SECRET", "a" * 48)
    get_settings.cache_clear()


def _tool_resp(calls: list[tuple[str, str, str]]) -> SimpleNamespace:
    tcs = [
        SimpleNamespace(id=cid, function=SimpleNamespace(name=name, arguments=args))
        for cid, name, args in calls
    ]
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=tcs))]
    )


def _text_resp(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text, tool_calls=None))]
    )


async def _collect(ctx: Any, **kwargs: Any) -> list[dict[str, Any]]:
    return [event async for event in run_agent(ctx, **kwargs)]


async def test_happy_path_search_cite_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = iter(
        [
            _tool_resp([("c1", "search_docs", '{"query": "what is x"}')]),
            _tool_resp([("c2", "cite_sources", '{"chunk_ids": ["abc"]}')]),
            _text_resp("X is a thing."),
        ]
    )

    async def fake_acompletion(**kwargs: Any) -> SimpleNamespace:
        return next(responses)

    async def fake_execute(name: str, args: dict[str, Any], ctx: Any) -> dict[str, Any]:
        if name == "search_docs":
            return {"results": [{"chunk_id": "abc", "snippet": "..."}]}
        if name == "cite_sources":
            return {"citations": [{"chunk_id": "abc", "document_title": "Doc"}]}
        return {"error": "unexpected"}

    monkeypatch.setattr(loop_module.litellm, "acompletion", fake_acompletion)
    monkeypatch.setattr(loop_module, "execute_tool", fake_execute)

    events = await _collect(None, system_prompt="sys", history=[], user_message="what is x")
    types = [e["type"] for e in events]
    assert types == ["tool_call", "tool_result", "tool_call", "tool_result", "answer"]
    answer = events[-1]
    assert answer["content"] == "X is a thing."
    assert answer["citations"] == [{"chunk_id": "abc", "document_title": "Doc"}]
    assert "truncated" not in answer  # clean finish


async def test_circuit_breaker_trips_on_repeated_call(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_acompletion(**kwargs: Any) -> SimpleNamespace:
        if "tools" in kwargs:
            # Always the same call+args → duplicates accumulate.
            return _tool_resp([("c", "search_docs", '{"query": "same"}')])
        return _text_resp("Forced final answer.")

    async def fake_execute(name: str, args: dict[str, Any], ctx: Any) -> dict[str, Any]:
        return {"results": []}

    monkeypatch.setattr(loop_module.litellm, "acompletion", fake_acompletion)
    monkeypatch.setattr(loop_module, "execute_tool", fake_execute)

    events = await _collect(None, system_prompt="sys", history=[], user_message="q")
    answer = events[-1]
    assert answer["type"] == "answer"
    assert answer["content"] == "Forced final answer."
    assert answer["truncated"] is True
    # The duplicate call surfaced as a failed tool_result before the break.
    assert any(e["type"] == "tool_result" and not e["ok"] for e in events)


async def test_max_iterations_forces_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    counter = {"n": 0}

    async def fake_acompletion(**kwargs: Any) -> SimpleNamespace:
        if "tools" in kwargs:
            counter["n"] += 1
            return _tool_resp([("c", "search_docs", f'{{"query": "q{counter["n"]}"}}')])
        return _text_resp("Best effort.")

    async def fake_execute(name: str, args: dict[str, Any], ctx: Any) -> dict[str, Any]:
        return {"results": []}

    monkeypatch.setattr(loop_module.litellm, "acompletion", fake_acompletion)
    monkeypatch.setattr(loop_module, "execute_tool", fake_execute)

    events = await _collect(
        None, system_prompt="sys", history=[], user_message="q", max_iterations=2
    )
    assert counter["n"] == 2  # capped at max_iterations
    assert events[-1] == {
        "type": "answer",
        "content": "Best effort.",
        "citations": [],
        "truncated": True,
    }


async def test_malformed_tool_arguments_are_tolerated(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = iter(
        [
            _tool_resp([("c1", "search_docs", "this is not json")]),
            _text_resp("Done."),
        ]
    )
    received: dict[str, Any] = {}

    async def fake_acompletion(**kwargs: Any) -> SimpleNamespace:
        return next(responses)

    async def fake_execute(name: str, args: dict[str, Any], ctx: Any) -> dict[str, Any]:
        received["args"] = args
        return {"results": []}

    monkeypatch.setattr(loop_module.litellm, "acompletion", fake_acompletion)
    monkeypatch.setattr(loop_module, "execute_tool", fake_execute)

    events = await _collect(None, system_prompt="sys", history=[], user_message="q")
    assert received["args"] == {}  # malformed JSON → empty args, no crash
    assert events[-1]["content"] == "Done."
