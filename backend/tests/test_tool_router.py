"""Tests for the two-stage tool router (gate + flash-LLM intent + execute)."""

import pytest

from app.services.llm.base import BaseLLM
from app.services.tools import registry
from app.services.tools.base import Tool, ToolResult
from app.services import tool_router


class FakeLLM(BaseLLM):
    def __init__(self, structured: dict | None = None):
        self.structured = structured or {}
        self.calls = 0

    async def generate(self, messages, system_prompt="", temperature=0.7):
        return "ok"

    async def generate_structured(self, messages, system_prompt="", schema=None, temperature=0.7):
        self.calls += 1
        return self.structured

    async def embed(self, text):
        return [0.0]


@pytest.fixture(autouse=True)
def fake_tools():
    saved = dict(registry._TOOLS)
    registry._TOOLS.clear()

    async def _exec(params: dict) -> ToolResult:
        return ToolResult(ok=True, summary=f"天气结果 city={params.get('city', '')}")

    registry.register(Tool(
        name="weather", display_name="天气查询", description="查天气",
        trigger_hints=["天气"], params_schema={"city": "城市"}, execute=_exec,
    ))
    yield
    registry._TOOLS.clear()
    registry._TOOLS.update(saved)


@pytest.mark.asyncio
async def test_gate_miss_skips_router_llm():
    llm = FakeLLM()
    result = await tool_router.route_and_execute("我今天好开心呀", llm)
    assert result is None
    assert llm.calls == 0  # 门控未命中，不应调用路由 LLM


@pytest.mark.asyncio
async def test_router_declines():
    llm = FakeLLM(structured={"tool": None, "params": {}})
    result = await tool_router.route_and_execute("今天天气真好，心情也好", llm)
    assert result is None
    assert llm.calls == 1


@pytest.mark.asyncio
async def test_router_executes_tool():
    llm = FakeLLM(structured={"tool": "weather", "params": {"city": "上海"}})
    routed = await tool_router.route_and_execute("上海天气怎么样", llm)
    assert routed is not None
    display_name, result = routed
    assert display_name == "天气查询"
    assert result.ok is True
    assert "city=上海" in result.summary


@pytest.mark.asyncio
async def test_router_unknown_tool():
    llm = FakeLLM(structured={"tool": "not_a_tool", "params": {}})
    result = await tool_router.route_and_execute("天气怎么样", llm)
    assert result is None


@pytest.mark.asyncio
async def test_router_llm_exception_is_safe(monkeypatch):
    llm = FakeLLM()

    async def boom(*args, **kwargs):
        raise RuntimeError("llm down")

    monkeypatch.setattr(llm, "generate_structured", boom)
    result = await tool_router.route_and_execute("天气怎么样", llm)
    assert result is None  # 路由失败不阻塞聊天


@pytest.mark.asyncio
async def test_tool_timeout_returns_failed_result():
    import asyncio

    async def slow_exec(params: dict) -> ToolResult:
        await asyncio.sleep(5)
        return ToolResult(ok=True, summary="too late")

    registry._TOOLS["weather"].execute = slow_exec
    registry._TOOLS["weather"].timeout = 0  # 立即超时
    llm = FakeLLM(structured={"tool": "weather", "params": {}})
    routed = await tool_router.route_and_execute("天气怎么样", llm)
    assert routed is not None
    _, result = routed
    assert result.ok is False
