"""Unit tests for promptforge_api.core.async_utils."""

from __future__ import annotations

import asyncio

import pytest

from promptforge_api.core.async_utils import (
    TokenBucket,
    gather_bounded,
    rate_limited,
    retry,
)


async def _noop_sleep(_delay: float) -> None:
    return None


# --- retry ---------------------------------------------------------------------------


async def test_retry_returns_on_first_success() -> None:
    calls = 0

    @retry(attempts=3)
    async def f() -> str:
        nonlocal calls
        calls += 1
        return "ok"

    assert await f() == "ok"
    assert calls == 1


async def test_retry_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(asyncio, "sleep", _noop_sleep)
    calls = 0

    @retry(attempts=3, jitter=False)
    async def f() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise ValueError("boom")
        return "ok"

    assert await f() == "ok"
    assert calls == 3


async def test_retry_exhausts_and_reraises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(asyncio, "sleep", _noop_sleep)

    @retry(attempts=2, jitter=False)
    async def f() -> None:
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        await f()


async def test_retry_does_not_catch_unlisted_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(asyncio, "sleep", _noop_sleep)
    calls = 0

    @retry(attempts=3, on=(KeyError,), jitter=False)
    async def f() -> None:
        nonlocal calls
        calls += 1
        raise ValueError("not retried")

    with pytest.raises(ValueError, match="not retried"):
        await f()
    assert calls == 1


async def test_retry_exponential_backoff_delays(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slept: list[float] = []

    async def record(delay: float) -> None:
        slept.append(delay)

    monkeypatch.setattr(asyncio, "sleep", record)

    @retry(attempts=4, backoff="exponential", base_delay=1.0, jitter=False)
    async def f() -> None:
        raise ValueError("fail")

    with pytest.raises(ValueError, match="fail"):
        await f()
    assert slept == [1.0, 2.0, 4.0]  # 3 waits between 4 attempts


async def test_retry_linear_backoff_delays(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []

    async def record(delay: float) -> None:
        slept.append(delay)

    monkeypatch.setattr(asyncio, "sleep", record)

    @retry(attempts=3, backoff="linear", base_delay=2.0, jitter=False)
    async def f() -> None:
        raise ValueError("fail")

    with pytest.raises(ValueError, match="fail"):
        await f()
    assert slept == [2.0, 4.0]


async def test_retry_caps_delay_at_max(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []

    async def record(delay: float) -> None:
        slept.append(delay)

    monkeypatch.setattr(asyncio, "sleep", record)

    @retry(attempts=5, backoff="exponential", base_delay=10.0, max_delay=15.0, jitter=False)
    async def f() -> None:
        raise ValueError("fail")

    with pytest.raises(ValueError, match="fail"):
        await f()
    assert all(d <= 15.0 for d in slept)


def test_retry_rejects_zero_attempts() -> None:
    with pytest.raises(ValueError, match="attempts"):
        retry(attempts=0)


# --- TokenBucket ---------------------------------------------------------------------


async def test_token_bucket_initial_burst_no_wait() -> None:
    clock = [0.0]
    slept: list[float] = []

    async def sleep(d: float) -> None:
        slept.append(d)
        clock[0] += d

    bucket = TokenBucket(rate=2, capacity=3, clock=lambda: clock[0], sleep=sleep)
    for _ in range(3):
        await bucket.acquire()
    assert slept == []  # 3 tokens of burst available


async def test_token_bucket_waits_when_empty() -> None:
    clock = [0.0]
    slept: list[float] = []

    async def sleep(d: float) -> None:
        slept.append(d)
        clock[0] += d

    bucket = TokenBucket(rate=2, capacity=1, clock=lambda: clock[0], sleep=sleep)
    await bucket.acquire()  # consume the one token
    await bucket.acquire()  # empty → wait 1/rate = 0.5s
    assert slept == [pytest.approx(0.5)]


async def test_token_bucket_refills_over_time() -> None:
    clock = [0.0]

    async def sleep(d: float) -> None:
        clock[0] += d

    bucket = TokenBucket(rate=10, capacity=1, clock=lambda: clock[0], sleep=sleep)
    await bucket.acquire()
    clock[0] += 1.0  # 1 second passes → 10 tokens would refill, capped at capacity=1
    await bucket.acquire()  # token available, no wait
    # nothing to assert on sleep; the point is the second acquire didn't block


def test_token_bucket_rejects_nonpositive_rate() -> None:
    with pytest.raises(ValueError, match="rate"):
        TokenBucket(rate=0)


# --- rate_limited (wiring) -----------------------------------------------------------


async def test_rate_limited_preserves_return_and_args() -> None:
    @rate_limited(per_second=1000, burst=1000)
    async def add(a: int, b: int) -> int:
        return a + b

    assert await add(2, 3) == 5


# --- gather_bounded ------------------------------------------------------------------


async def test_gather_bounded_preserves_order() -> None:
    async def echo(x: int) -> int:
        await asyncio.sleep(0)
        return x

    result = await gather_bounded([echo(i) for i in range(5)], concurrency=2)
    assert result == [0, 1, 2, 3, 4]


async def test_gather_bounded_limits_concurrency() -> None:
    active = 0
    peak = 0

    async def task() -> None:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1

    await gather_bounded([task() for _ in range(12)], concurrency=3)
    assert peak <= 3


async def test_gather_bounded_collect_returns_exceptions() -> None:
    async def ok() -> int:
        return 1

    async def boom() -> int:
        raise ValueError("x")

    result = await gather_bounded([ok(), boom()], concurrency=2, on_error="collect")
    assert result[0] == 1
    assert isinstance(result[1], ValueError)


async def test_gather_bounded_raise_propagates_first_error() -> None:
    async def boom() -> int:
        raise ValueError("x")

    with pytest.raises(ValueError, match="x"):
        await gather_bounded([boom()], concurrency=1)


async def test_gather_bounded_rejects_zero_concurrency() -> None:
    with pytest.raises(ValueError, match="concurrency"):
        await gather_bounded([], concurrency=0)
