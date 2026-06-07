"""Unit: tool schemas, dispatcher routing, pure helpers."""

from typing import cast
from uuid import uuid4

from promptforge_ragent.agent.tools import (
    TOOL_SCHEMAS,
    ToolContext,
    _parse_uuid,
    _snippet,
    execute_tool,
)


def test_tool_schemas_shape() -> None:
    names = {t["function"]["name"] for t in TOOL_SCHEMAS}
    assert names == {"search_docs", "fetch_passage", "cite_sources"}
    for tool in TOOL_SCHEMAS:
        fn = tool["function"]
        assert tool["type"] == "function"
        assert fn["description"]
        assert fn["parameters"]["type"] == "object"
        assert fn["parameters"]["required"]  # every tool has a required arg


def test_snippet_truncates_with_ellipsis() -> None:
    assert _snippet("short") == "short"
    long = "x" * 400
    out = _snippet(long, limit=280)
    assert len(out) == 281  # 280 chars + ellipsis
    assert out.endswith("…")


def test_parse_uuid() -> None:
    u = uuid4()
    assert _parse_uuid(str(u)) == u
    assert _parse_uuid("not-a-uuid") is None
    assert _parse_uuid(None) is None


async def test_execute_unknown_tool_returns_error() -> None:
    ctx = cast(ToolContext, ToolContext(session=None, corpus=None))  # type: ignore[arg-type]
    out = await execute_tool("nonexistent", {}, ctx)
    assert "error" in out
    assert "unknown tool" in out["error"]
