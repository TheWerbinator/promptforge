"""LLM provider wrapper.

Single async `call_llm` that's used by `services.eval_runner` (phase 11) and the
single-run `POST /run` endpoint (phase 10). litellm handles provider routing via
the `provider/model` prefix — switching from gpt-4o-mini to claude-haiku-4-5 is
a string change, not a refactor.

Retry policy: only transient errors (network, timeout, rate-limit) are retried.
Auth failures and 4xx invalid-request errors propagate immediately — retrying
them is a waste of attempts and money. The global token bucket caps our hosted
demo at 10 req/s; BYOK calls bypass it because they consume the user's quota,
not ours.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import litellm
from litellm.exceptions import (
    APIConnectionError,
    APIError,
    RateLimitError,
    Timeout,
)

from promptforge_api.core.async_utils import TokenBucket, retry

_RETRYABLE: tuple[type[BaseException], ...] = (
    APIConnectionError,
    Timeout,
    RateLimitError,
    APIError,  # general server-side; usually retryable
)

# Global limiter for our hosted demo key. BYOK calls skip it.
_DEFAULT_RATE = TokenBucket(rate=10, capacity=10)


@dataclass(frozen=True)
class LLMResponse:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    latency_ms: int
    provider_response: dict[str, Any] = field(repr=False)


class LLMCallError(RuntimeError):
    """Raised when an LLM call fails permanently (after retries exhausted or
    on non-retryable provider error)."""


@retry(
    attempts=3,
    backoff="exponential",
    base_delay=1.0,
    max_delay=30.0,
    on=_RETRYABLE,
)
async def _acompletion_with_retry(**kwargs: Any) -> Any:
    return await litellm.acompletion(**kwargs)


async def call_llm(
    model: str,
    messages: list[dict[str, Any]],
    *,
    max_tokens: int = 1024,
    temperature: float = 0.7,
    response_format: dict[str, Any] | None = None,
    user_api_key: str | None = None,
    timeout: float = 60.0,  # noqa: ASYNC109 -- forwarded to litellm HTTP client, not asyncio.timeout
    extra: dict[str, Any] | None = None,
) -> LLMResponse:
    """Single async LLM call.

    `model` follows litellm's `provider/model` convention (e.g.
    `openai/gpt-4o-mini`, `anthropic/claude-haiku-4-5-20251001`).

    `user_api_key` activates BYOK: the key flows through to the provider call
    instead of using the server's configured key, and the global rate limiter
    is skipped (the user is hitting their own quota).
    """
    if user_api_key is None:
        await _DEFAULT_RATE.acquire()

    call_kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "timeout": timeout,
    }
    if response_format is not None:
        call_kwargs["response_format"] = response_format
    if user_api_key is not None:
        call_kwargs["api_key"] = user_api_key
    if extra:
        call_kwargs.update(extra)

    start = time.monotonic()
    try:
        response = await _acompletion_with_retry(**call_kwargs)
    except _RETRYABLE as exc:  # retries exhausted
        raise LLMCallError(f"{model}: transient error after retries: {exc}") from exc
    except Exception as exc:  # auth, invalid-request, etc. — propagate, no retry
        raise LLMCallError(f"{model}: {type(exc).__name__}: {exc}") from exc

    latency_ms = int((time.monotonic() - start) * 1000)
    return _parse_response(response, model=model, latency_ms=latency_ms)


def _parse_response(response: Any, *, model: str, latency_ms: int) -> LLMResponse:
    """Pull text, tokens, and cost out of a litellm ModelResponse."""
    text = ""
    choices = getattr(response, "choices", None) or []
    if choices:
        message = getattr(choices[0], "message", None)
        text = getattr(message, "content", "") or ""

    usage = getattr(response, "usage", None)
    input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)

    cost_usd: float | None
    try:
        cost_usd = float(litellm.completion_cost(completion_response=response))
    except Exception:
        # Unknown model, missing pricing, or experimental provider. Surface as
        # None rather than crashing — the Run row still persists, just without cost.
        cost_usd = None

    raw: dict[str, Any]
    if hasattr(response, "model_dump"):
        raw = response.model_dump()
    elif hasattr(response, "dict"):
        raw = response.dict()
    else:
        raw = {}

    return LLMResponse(
        text=text,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        provider_response=raw,
    )
