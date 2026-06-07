"""The ReAct agent loop: litellm function-calling over the three tools.

Each turn the model either calls tools or gives a final answer. We run tool calls
through `execute_tool`, append the results, and loop — bounded by two safety
rails: a max-iteration cap, and a circuit breaker that trips when the model
repeats the *same* tool with the *same* arguments (a common stuck-loop failure).
When either rail fires we make one tool-less completion to force a coherent final
answer rather than dumping a half-finished transcript.

`run_agent` is an async generator of small JSON-serializable events
(`tool_call`, `tool_result`, `answer`) so the Phase-9 chat route can map them
straight to SSE. Citations declared via `cite_sources` ride out on the final
`answer` event.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import litellm
import structlog

from promptforge_ragent.agent.tools import TOOL_SCHEMAS, ToolContext, execute_tool
from promptforge_ragent.core.config import get_settings

log = structlog.get_logger("promptforge.ragent.loop")

_MAX_DUPLICATE_CALLS = 2  # circuit breaker: trip after this many repeated tool+args


def _assistant_message(content: str | None, tool_calls: list[Any]) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": content or "",
        "tool_calls": [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in tool_calls
        ],
    }


def _summarize(name: str, result: dict[str, Any]) -> str:
    if "error" in result:
        return f"error: {result['error']}"
    if name == "search_docs":
        return f"{len(result.get('results', []))} results"
    if name == "cite_sources":
        return f"{len(result.get('citations', []))} citations"
    if name == "fetch_passage":
        return "passage fetched"
    return "ok"


async def _complete(
    model: str, messages: list[dict[str, Any]], *, api_key: str | None, with_tools: bool
) -> Any:
    kwargs: dict[str, Any] = {"model": model, "messages": messages, "api_key": api_key}
    if with_tools:
        kwargs["tools"] = TOOL_SCHEMAS
        kwargs["tool_choice"] = "auto"
    return await litellm.acompletion(**kwargs)


async def run_agent(
    ctx: ToolContext,
    *,
    system_prompt: str,
    history: list[dict[str, Any]],
    user_message: str,
    model: str | None = None,
    max_iterations: int | None = None,
    api_key: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Drive the ReAct loop, yielding tool_call / tool_result / answer events."""
    settings = get_settings()
    model = model or settings.agent_model
    max_iterations = max_iterations or settings.agent_max_iterations
    if api_key is None and settings.openai_api_key is not None:
        api_key = settings.openai_api_key.get_secret_value()

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        *history,
        {"role": "user", "content": user_message},
    ]
    seen_calls: set[str] = set()
    duplicates = 0
    citations: list[dict[str, Any]] = []

    for _ in range(max_iterations):
        response = await _complete(model, messages, api_key=api_key, with_tools=True)
        message = response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None)

        if not tool_calls:
            yield {"type": "answer", "content": message.content or "", "citations": citations}
            return

        messages.append(_assistant_message(message.content, tool_calls))
        for tc in tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            yield {"type": "tool_call", "tool": name, "arguments": args}

            signature = f"{name}:{json.dumps(args, sort_keys=True, default=str)}"
            if signature in seen_calls:
                duplicates += 1
                result: dict[str, Any] = {
                    "error": "duplicate call: you already ran this exact query. "
                    "Try different arguments or give your final answer."
                }
            else:
                seen_calls.add(signature)
                result = await execute_tool(name, args, ctx)
                if name == "cite_sources" and "citations" in result:
                    citations = result["citations"]

            yield {
                "type": "tool_result",
                "tool": name,
                "ok": "error" not in result,
                "summary": _summarize(name, result),
            }
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)})

        if duplicates >= _MAX_DUPLICATE_CALLS:
            log.info("agent_circuit_breaker_tripped")
            break

    # Max iterations or breaker: force one tool-less answer from what we have.
    messages.append(
        {
            "role": "system",
            "content": "Give your best final answer now using the information gathered. "
            "Do not call any tools.",
        }
    )
    final = await _complete(model, messages, api_key=api_key, with_tools=False)
    yield {
        "type": "answer",
        "content": final.choices[0].message.content or "",
        "citations": citations,
        "truncated": True,
    }
