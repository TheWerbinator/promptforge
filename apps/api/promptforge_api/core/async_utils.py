"""Async orchestration primitives: retry, rate limiting, bounded fan-out.

These back the eval runner's parallel LLM calls (phase 11) — fire N prompt
evaluations at once, but cap concurrency, retry transient provider errors with
backoff, and stay under the provider's requests-per-second ceiling.

Considered tenacity (retry) and aiolimiter (rate limiting). Kept these in-house:
they're ~100 lines total, this module is the async-orchestration showcase of the
repo, and pulling two dependencies for that surface area isn't worth it. I'd adopt
tenacity if retry policies grew into per-exception strategies or stop conditions.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable, Iterable
from functools import wraps
from typing import Literal, ParamSpec, TypeVar, overload

P = ParamSpec("P")
T = TypeVar("T")

BackoffStrategy = Literal["constant", "linear", "exponential"]


def _delay_for(
    backoff: BackoffStrategy,
    base: float,
    max_delay: float,
    attempt: int,
    jitter: bool,
) -> float:
    if backoff == "constant":
        raw = base
    elif backoff == "linear":
        raw = base * attempt
    else:
        raw = base * (2 ** (attempt - 1))
    raw = min(raw, max_delay)
    if jitter:
        # Equal jitter: half fixed, half random. Spreads retries without ever
        # collapsing to a zero wait. random is fine here — not security-sensitive.
        raw = raw / 2 + random.uniform(0, raw / 2)  # noqa: S311
    return raw


def retry(
    *,
    attempts: int = 3,
    backoff: BackoffStrategy = "exponential",
    base_delay: float = 0.5,
    max_delay: float = 10.0,
    jitter: bool = True,
    on: tuple[type[BaseException], ...] = (Exception,),
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    """Retry an async function on `on` exceptions with backoff between attempts."""
    if attempts < 1:
        raise ValueError("attempts must be >= 1")

    def decorator(fn: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        @wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            for attempt in range(1, attempts + 1):
                try:
                    return await fn(*args, **kwargs)
                except on:
                    if attempt == attempts:
                        raise
                    await asyncio.sleep(_delay_for(backoff, base_delay, max_delay, attempt, jitter))
            raise AssertionError("unreachable")  # pragma: no cover

        return wrapper

    return decorator


class TokenBucket:
    """Async token bucket. `clock`/`sleep` are injectable so the pacing logic is
    testable without real wall-clock waits."""

    def __init__(
        self,
        rate: float,
        capacity: float | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if rate <= 0:
            raise ValueError("rate must be > 0")
        self.rate = rate
        self.capacity = capacity if capacity is not None else rate
        self._tokens = float(self.capacity)
        self._clock = clock
        self._sleep = sleep
        self._updated = clock()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = self._clock()
            self._tokens = min(self.capacity, self._tokens + (now - self._updated) * self.rate)
            self._updated = now
            if self._tokens < 1:
                wait = (1 - self._tokens) / self.rate
                await self._sleep(wait)
                self._tokens = 0.0
                self._updated = self._clock()
            else:
                self._tokens -= 1


def rate_limited(
    per_second: float, *, burst: int | None = None
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    """Cap calls to a decorated async function at `per_second` (with optional burst).

    One bucket is shared across all calls to the decorated function, so the limit
    is global for that callable — exactly what we want for "≤10 LLM req/s".
    """
    bucket = TokenBucket(per_second, burst)

    def decorator(fn: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        @wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            await bucket.acquire()
            return await fn(*args, **kwargs)

        return wrapper

    return decorator


@overload
async def gather_bounded(
    coros: Iterable[Awaitable[T]],
    *,
    concurrency: int,
    on_error: Literal["raise"] = "raise",
) -> list[T]: ...


@overload
async def gather_bounded(
    coros: Iterable[Awaitable[T]],
    *,
    concurrency: int,
    on_error: Literal["collect"],
) -> list[T | BaseException]: ...


async def gather_bounded(
    coros: Iterable[Awaitable[T]],
    *,
    concurrency: int,
    on_error: Literal["raise", "collect"] = "raise",
) -> list[T] | list[T | BaseException]:
    """Run awaitables with at most `concurrency` in flight, preserving input order.

    on_error="raise": first exception propagates and pending tasks are cancelled.
    on_error="collect": exceptions are returned in place of results.
    """
    if concurrency < 1:
        raise ValueError("concurrency must be >= 1")

    sem = asyncio.Semaphore(concurrency)

    async def _run(coro: Awaitable[T]) -> T:
        async with sem:
            return await coro

    tasks = [asyncio.ensure_future(_run(c)) for c in coros]
    try:
        if on_error == "collect":
            return await asyncio.gather(*tasks, return_exceptions=True)
        return await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            if not task.done():
                task.cancel()
        raise
