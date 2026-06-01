"""Eval worker process.

Runs as a second Fly process alongside the api (see fly.toml [processes]).
Consumes jobs of kind="eval_case" — implementation lands in phase 11 once the
eval engine exists. For phase 8 this is a skeleton that proves the worker can
boot, attach to the shared DB, and poll the queue.

Entry: `python -m promptforge_api.workers.eval_worker`
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from typing import Any

from promptforge_api.core.db import get_session_factory
from promptforge_api.core.queue import ClaimedJob, Queue
from promptforge_api.services.eval_runner import run_eval_case

log = logging.getLogger("promptforge.worker")


async def _handle_eval_case(payload: dict[str, Any]) -> None:
    log.info(
        "eval_case start batch=%s case=%s",
        payload.get("batch_id"),
        payload.get("case_id"),
    )
    await run_eval_case(payload, session_factory=get_session_factory())


HANDLERS = {
    "eval_case": _handle_eval_case,
}


async def _consume_forever(queue: Queue, stop: asyncio.Event) -> None:
    async with queue.consume("eval_case", batch_size=4) as stream:
        async for job in stream:
            if stop.is_set():
                break
            await _run_one(job)


async def _run_one(job: ClaimedJob) -> None:
    handler = HANDLERS.get(job.kind)
    if handler is None:
        # Unknown kind — fail it explicitly so it doesn't retry forever.
        async with job:
            raise RuntimeError(f"no handler registered for kind={job.kind!r}")
        return
    async with job:
        await handler(job.payload)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    queue = Queue(get_session_factory())

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        # Windows: signal handlers in asyncio loops are unsupported. The worker
        # still exits cleanly on Ctrl+C via KeyboardInterrupt.
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)

    consumer = asyncio.create_task(_consume_forever(queue, stop))
    log.info("eval_worker started; polling kind=eval_case")
    await stop.wait()
    log.info("eval_worker shutting down")
    consumer.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await consumer


if __name__ == "__main__":
    asyncio.run(main())
