"""Unit tests for the 4 eval judges. LLM-judge mocks call_llm."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from promptforge_api.models import JudgeKind
from promptforge_api.services import judge as judge_module
from promptforge_api.services.judge import JudgeOutcome, judge


async def test_exact_match_passes() -> None:
    result = await judge(JudgeKind.EXACT, output="hello", expected={"value": "hello"})
    assert result.passed is True
    assert result.score == 1.0


async def test_exact_match_trims_whitespace() -> None:
    result = await judge(JudgeKind.EXACT, output="  hello  \n", expected={"value": "hello"})
    assert result.passed is True


async def test_exact_mismatch_fails() -> None:
    result = await judge(JudgeKind.EXACT, output="goodbye", expected={"value": "hello"})
    assert result.passed is False
    assert result.score == 0.0


async def test_contains_default_case_insensitive() -> None:
    result = await judge(JudgeKind.CONTAINS, output="Hello World", expected={"value": "hello"})
    assert result.passed is True


async def test_contains_case_sensitive_flag() -> None:
    result = await judge(
        JudgeKind.CONTAINS,
        output="Hello World",
        expected={"value": "hello"},
        config={"case_sensitive": True},
    )
    assert result.passed is False


async def test_regex_match() -> None:
    result = await judge(JudgeKind.REGEX, output="order #1234", expected={"pattern": r"#\d+"})
    assert result.passed is True


async def test_regex_ignore_case_flag() -> None:
    result = await judge(
        JudgeKind.REGEX,
        output="HELLO",
        expected={"pattern": "hello"},
        config={"flags": "i"},
    )
    assert result.passed is True


async def test_regex_no_match() -> None:
    result = await judge(JudgeKind.REGEX, output="nope", expected={"pattern": r"^yes$"})
    assert result.passed is False


async def test_regex_invalid_pattern_fails_gracefully() -> None:
    result = await judge(JudgeKind.REGEX, output="anything", expected={"pattern": "[unclosed"})
    assert result.passed is False
    assert "invalid regex" in (result.reasoning or "")


async def test_llm_judge_passes_at_or_above_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(text='{"score": 0.85, "reasoning": "covers the criterion"}')

    monkeypatch.setattr(judge_module.llm_service, "call_llm", _fake)

    outcome = await judge(
        JudgeKind.LLM_JUDGE,
        output="answer",
        expected={"rubric": "be helpful", "criterion": "addresses the question"},
        config={"threshold": 0.7},
    )
    assert isinstance(outcome, JudgeOutcome)
    assert outcome.passed is True
    assert outcome.score == 0.85


async def test_llm_judge_fails_below_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(text='{"score": 0.4, "reasoning": "missed key point"}')

    monkeypatch.setattr(judge_module.llm_service, "call_llm", _fake)

    outcome = await judge(
        JudgeKind.LLM_JUDGE,
        output="x",
        expected={"rubric": "r", "criterion": "c"},
        config={"threshold": 0.7},
    )
    assert outcome.passed is False


async def test_llm_judge_clamps_score_to_unit_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(text='{"score": 1.5, "reasoning": "overshot"}')

    monkeypatch.setattr(judge_module.llm_service, "call_llm", _fake)
    outcome = await judge(
        JudgeKind.LLM_JUDGE,
        output="x",
        expected={"rubric": "r", "criterion": "c"},
    )
    assert outcome.score == 1.0


async def test_llm_judge_handles_non_json(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(text="not json at all")

    monkeypatch.setattr(judge_module.llm_service, "call_llm", _fake)
    outcome = await judge(
        JudgeKind.LLM_JUDGE,
        output="x",
        expected={"rubric": "r", "criterion": "c"},
    )
    assert outcome.passed is False
    assert outcome.score == 0.0


async def test_llm_judge_handles_call_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from promptforge_api.services.llm import LLMCallError

    async def _boom(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        raise LLMCallError("provider down")

    monkeypatch.setattr(judge_module.llm_service, "call_llm", _boom)
    outcome = await judge(
        JudgeKind.LLM_JUDGE,
        output="x",
        expected={"rubric": "r", "criterion": "c"},
    )
    assert outcome.passed is False
    assert "judge LLM call failed" in (outcome.reasoning or "")
