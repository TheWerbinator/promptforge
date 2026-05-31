"""Unit tests for services/llm.py with litellm.acompletion fully mocked.

We never call a real provider in tests — they're slow, cost money, and depend on
external availability. The mock returns a hand-built object shaped like a litellm
ModelResponse (choices[0].message.content + usage.prompt/completion_tokens).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import litellm
import pytest
from litellm.exceptions import (
    AuthenticationError,
    BadRequestError,
    RateLimitError,
    Timeout,
)

from promptforge_api.services import llm as llm_module
from promptforge_api.services.llm import LLMCallError, call_llm


def _fake_response(
    text: str = "hello",
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
) -> SimpleNamespace:
    message = SimpleNamespace(content=text)
    choice = SimpleNamespace(message=message)
    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
    return SimpleNamespace(
        choices=[choice],
        usage=usage,
        model_dump=lambda: {"choices": [{"message": {"content": text}}]},
    )


@pytest.fixture(autouse=True)
def _isolate_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the global rate limiter so tests never sleep on token refill."""
    from promptforge_api.core.async_utils import TokenBucket

    monkeypatch.setattr(
        llm_module,
        "_DEFAULT_RATE",
        TokenBucket(rate=1_000_000, capacity=1_000_000),
    )


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """retry()'s backoff calls asyncio.sleep; replace with a no-op so retry tests
    don't actually wait between attempts."""

    async def _instant(_delay: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _instant)


async def test_call_llm_returns_parsed_response(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake(**_kwargs: Any) -> SimpleNamespace:
        return _fake_response(text="hi", prompt_tokens=12, completion_tokens=3)

    monkeypatch.setattr(litellm, "acompletion", _fake)
    monkeypatch.setattr(litellm, "completion_cost", lambda **_: 0.0001)

    result = await call_llm("openai/gpt-4o-mini", [{"role": "user", "content": "hi"}])
    assert result.text == "hi"
    assert result.model == "openai/gpt-4o-mini"
    assert result.input_tokens == 12
    assert result.output_tokens == 3
    assert result.cost_usd == 0.0001
    assert result.latency_ms >= 0


async def test_call_llm_handles_missing_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake(**_kwargs: Any) -> SimpleNamespace:
        return _fake_response()

    def _no_cost(**_kwargs: Any) -> float:
        raise ValueError("unknown model")

    monkeypatch.setattr(litellm, "acompletion", _fake)
    monkeypatch.setattr(litellm, "completion_cost", _no_cost)

    result = await call_llm("custom/local-model", [{"role": "user", "content": "x"}])
    assert result.cost_usd is None
    assert result.text == "hello"


async def test_call_llm_retries_transient_then_succeeds(
    monkeypatch: pytest.MonkeyPatch, no_sleep: None
) -> None:
    calls = 0

    async def _fake(**_kwargs: Any) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise Timeout(
                message="slow",
                model="openai/gpt-4o-mini",
                llm_provider="openai",
            )
        return _fake_response()

    monkeypatch.setattr(litellm, "acompletion", _fake)
    monkeypatch.setattr(litellm, "completion_cost", lambda **_: 0.0)

    result = await call_llm("openai/gpt-4o-mini", [{"role": "user", "content": "x"}])
    assert result.text == "hello"
    assert calls == 3


async def test_call_llm_retry_exhausts_then_raises(
    monkeypatch: pytest.MonkeyPatch, no_sleep: None
) -> None:
    async def _fake(**_kwargs: Any) -> SimpleNamespace:
        raise RateLimitError(
            message="429",
            model="openai/gpt-4o-mini",
            llm_provider="openai",
        )

    monkeypatch.setattr(litellm, "acompletion", _fake)

    with pytest.raises(LLMCallError, match="transient"):
        await call_llm("openai/gpt-4o-mini", [{"role": "user", "content": "x"}])


async def test_call_llm_does_not_retry_auth_error(
    monkeypatch: pytest.MonkeyPatch, no_sleep: None
) -> None:
    calls = 0

    async def _fake(**_kwargs: Any) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        raise AuthenticationError(
            message="bad key",
            llm_provider="openai",
            model="openai/gpt-4o-mini",
        )

    monkeypatch.setattr(litellm, "acompletion", _fake)

    with pytest.raises(LLMCallError, match="AuthenticationError"):
        await call_llm("openai/gpt-4o-mini", [{"role": "user", "content": "x"}])
    assert calls == 1  # auth errors are NOT retried


async def test_call_llm_does_not_retry_bad_request(
    monkeypatch: pytest.MonkeyPatch, no_sleep: None
) -> None:
    calls = 0

    async def _fake(**_kwargs: Any) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        raise BadRequestError(
            message="invalid messages",
            model="openai/gpt-4o-mini",
            llm_provider="openai",
        )

    monkeypatch.setattr(litellm, "acompletion", _fake)

    with pytest.raises(LLMCallError):
        await call_llm("openai/gpt-4o-mini", [{"role": "user", "content": "x"}])
    assert calls == 1


async def test_byok_passes_api_key_and_skips_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    async def _fake(**kwargs: Any) -> SimpleNamespace:
        seen.update(kwargs)
        return _fake_response()

    monkeypatch.setattr(litellm, "acompletion", _fake)
    monkeypatch.setattr(litellm, "completion_cost", lambda **_: 0.0)

    # Mark the limiter so we can detect if BYOK accidentally hits it.
    acquired = False

    async def _track_acquire() -> None:
        nonlocal acquired
        acquired = True

    monkeypatch.setattr(llm_module._DEFAULT_RATE, "acquire", _track_acquire)

    await call_llm(
        "openai/gpt-4o-mini",
        [{"role": "user", "content": "x"}],
        user_api_key="sk-user-xxx",
    )
    assert seen["api_key"] == "sk-user-xxx"
    assert acquired is False


async def test_response_format_kwarg_passes_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    async def _fake(**kwargs: Any) -> SimpleNamespace:
        seen.update(kwargs)
        return _fake_response()

    monkeypatch.setattr(litellm, "acompletion", _fake)
    monkeypatch.setattr(litellm, "completion_cost", lambda **_: 0.0)

    await call_llm(
        "openai/gpt-4o-mini",
        [{"role": "user", "content": "x"}],
        response_format={"type": "json_object"},
    )
    assert seen["response_format"] == {"type": "json_object"}


async def test_extra_kwargs_merge(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def _fake(**kwargs: Any) -> SimpleNamespace:
        seen.update(kwargs)
        return _fake_response()

    monkeypatch.setattr(litellm, "acompletion", _fake)
    monkeypatch.setattr(litellm, "completion_cost", lambda **_: 0.0)

    await call_llm(
        "openai/gpt-4o-mini",
        [{"role": "user", "content": "x"}],
        extra={"top_p": 0.5},
    )
    assert seen["top_p"] == 0.5
