"""Tests for the tool registry — register/get/gate_match."""

import pytest

from app.services.tools.base import Tool, ToolResult
from app.services.tools import registry


@pytest.fixture(autouse=True)
def clean_registry():
    saved = dict(registry._TOOLS)
    registry._TOOLS.clear()
    yield
    registry._TOOLS.clear()
    registry._TOOLS.update(saved)


def _make_tool(name="demo", hints=None):
    async def _exec(params: dict) -> ToolResult:
        return ToolResult(ok=True, summary="demo result")

    return Tool(
        name=name,
        display_name="演示工具",
        description="一个演示工具",
        trigger_hints=hints or ["天气", "下雨"],
        params_schema={"city": "城市名"},
        execute=_exec,
    )


def test_register_and_get():
    tool = registry.register(_make_tool())
    assert registry.get_tool("demo") is tool
    assert registry.get_tool("nonexistent") is None
    assert registry.all_tools() == [tool]


def test_gate_match():
    registry.register(_make_tool())
    assert registry.gate_match("明天天气怎么样") is True
    assert registry.gate_match("我今天好开心") is False
    assert registry.gate_match("") is False


def test_tool_default_timeout():
    tool = _make_tool()
    assert tool.timeout == 10


@pytest.mark.asyncio
async def test_tool_execute_returns_result():
    tool = _make_tool()
    result = await tool.execute({})
    assert result.ok is True
    assert result.summary == "demo result"
