"""Eval judges — four strategies for scoring an LLM output against an expected.

Three deterministic judges (exact, contains, regex) and one model-graded
(llm_judge). The deterministic ones return score ∈ {0.0, 1.0}; llm_judge returns
the raw float the grader produced (clamped to [0, 1]).

`expected` shape is judge-specific:
  exact     → {"value": "..."}
  contains  → {"value": "..."}             + judge_config: {"case_sensitive": bool}
  regex     → {"pattern": "..."}           + judge_config: {"flags": "i"|"m"|"s"|""}
  llm_judge → {"rubric": "...", "criterion": "..."}
              judge_config: {"model": "openai/gpt-4o-mini", "threshold": 0.7}

Threshold default is 0.7 for llm_judge — anything ≥ threshold is passed=True.
Deterministic judges pass when score == 1.0.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from promptforge_api.models import JudgeKind
from promptforge_api.services import llm as llm_service


@dataclass(frozen=True)
class JudgeOutcome:
    score: float
    passed: bool
    reasoning: str | None = None


async def judge(
    kind: JudgeKind,
    *,
    output: str,
    expected: dict[str, Any],
    config: dict[str, Any] | None = None,
    user_api_key: str | None = None,
) -> JudgeOutcome:
    """Dispatch to the right judge. `user_api_key` is only used by llm_judge."""
    config = config or {}
    if kind is JudgeKind.EXACT:
        return _exact(output, expected)
    if kind is JudgeKind.CONTAINS:
        return _contains(output, expected, config)
    if kind is JudgeKind.REGEX:
        return _regex(output, expected, config)
    if kind is JudgeKind.LLM_JUDGE:
        return await _llm_judge(output, expected, config, user_api_key=user_api_key)
    raise ValueError(f"unknown judge kind: {kind!r}")


def _exact(output: str, expected: dict[str, Any]) -> JudgeOutcome:
    target = str(expected.get("value", ""))
    matched = output.strip() == target.strip()
    return JudgeOutcome(
        score=1.0 if matched else 0.0,
        passed=matched,
        reasoning="exact match" if matched else f"expected {target!r}, got {output[:80]!r}",
    )


def _contains(output: str, expected: dict[str, Any], config: dict[str, Any]) -> JudgeOutcome:
    target = str(expected.get("value", ""))
    case_sensitive = bool(config.get("case_sensitive", False))
    haystack = output if case_sensitive else output.lower()
    needle = target if case_sensitive else target.lower()
    matched = needle in haystack
    return JudgeOutcome(
        score=1.0 if matched else 0.0,
        passed=matched,
        reasoning=(f"output contains {target!r}" if matched else f"output missing {target!r}"),
    )


def _regex(output: str, expected: dict[str, Any], config: dict[str, Any]) -> JudgeOutcome:
    pattern = str(expected.get("pattern", ""))
    flag_chars = str(config.get("flags", ""))
    flags = 0
    if "i" in flag_chars:
        flags |= re.IGNORECASE
    if "m" in flag_chars:
        flags |= re.MULTILINE
    if "s" in flag_chars:
        flags |= re.DOTALL
    try:
        matched = re.search(pattern, output, flags) is not None
    except re.error as exc:
        return JudgeOutcome(score=0.0, passed=False, reasoning=f"invalid regex: {exc}")
    return JudgeOutcome(
        score=1.0 if matched else 0.0,
        passed=matched,
        reasoning=(f"regex {pattern!r} matched" if matched else f"regex {pattern!r} did not match"),
    )


_LLM_JUDGE_SYSTEM = (
    "You are an impartial grader. You will be given a model output and a rubric. "
    "Score the output from 0.0 to 1.0 according to the rubric. Respond with strict "
    "JSON only, no other text, of the form: "
    '{"score": <float>, "reasoning": "<one-sentence explanation>"}'
)


async def _llm_judge(
    output: str,
    expected: dict[str, Any],
    config: dict[str, Any],
    *,
    user_api_key: str | None,
) -> JudgeOutcome:
    rubric = str(expected.get("rubric", ""))
    criterion = str(expected.get("criterion", ""))
    threshold = float(config.get("threshold", 0.7))
    model = str(config.get("model", "openai/gpt-4o-mini"))

    user_prompt = (
        f"Rubric:\n{rubric}\n\n"
        f"Criterion to check: {criterion}\n\n"
        f"Model output:\n{output}\n\n"
        "Score the output."
    )

    try:
        result = await llm_service.call_llm(
            model,
            [
                {"role": "system", "content": _LLM_JUDGE_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=300,
            temperature=0.0,
            response_format={"type": "json_object"},
            user_api_key=user_api_key,
        )
    except llm_service.LLMCallError as exc:
        return JudgeOutcome(score=0.0, passed=False, reasoning=f"judge LLM call failed: {exc}")

    try:
        payload = json.loads(result.text)
        raw_score = float(payload.get("score", 0.0))
    except (json.JSONDecodeError, TypeError, ValueError):
        return JudgeOutcome(
            score=0.0,
            passed=False,
            reasoning=f"judge returned non-JSON: {result.text[:160]!r}",
        )

    score = max(0.0, min(1.0, raw_score))
    reasoning = str(payload.get("reasoning", ""))[:1000] if isinstance(payload, dict) else None
    return JudgeOutcome(score=score, passed=score >= threshold, reasoning=reasoning)
