"""Tests for runtime tool enable/disable."""

import pytest

from app.services.llm.base import BaseLLM
from app.services.tools import registry
from app.services.tools.base import Tool, ToolResult
from app.services import tool_router


class FakeLLM(BaseLLM):
    def __init__(self, structured=None):
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
    saved_disabled = set(registry._disabled)
    registry._TOOLS.clear()
    registry._disabled.clear()

    async def _exec(params: dict) -> ToolResult:
        return ToolResult(ok=True, summary="ok")

    registry.register(Tool(
        name="weather", display_name="天气查询", description="查天气",
        trigger_hints=["天气"], params_schema={}, execute=_exec,
    ))
    yield
    registry._TOOLS.clear()
    registry._TOOLS.update(saved)
    registry._disabled.clear()
    registry._disabled.update(saved_disabled)


def test_disable_filters_everything():
    assert registry.is_enabled("weather") is True
    assert registry.gate_match("天气怎么样") is True
    registry.set_tool_state("weather", False)
    assert registry.is_enabled("weather") is False
    assert registry.gate_match("天气怎么样") is False        # 门控不再命中
    assert registry.enabled_tools() == []                    # 路由 prompt 不再包含
    assert registry.get_tool("weather") is not None          # 注册表本身仍可查（心跳判断用）
    registry.set_tool_state("weather", True)
    assert registry.is_enabled("weather") is True


@pytest.mark.asyncio
async def test_router_skips_disabled_tool():
    registry.set_tool_state("weather", False)
    llm = FakeLLM(structured={"tool": "weather", "params": {}})
    result = await tool_router.route_and_execute("天气怎么样", llm)
    assert result is None
    assert llm.calls == 0  # 门控就被拦住，不付 LLM 调用


@pytest.mark.asyncio
async def test_heartbeat_skill_skips_disabled_tool(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.services import skills

    monkeypatch.setattr(skills, "_bump_usage", AsyncMock())
    registry.set_tool_state("weather", False)
    skill = SimpleNamespace(id="s1", name="天气查询", description="", execution_prompt=None,
                            tool_name="weather", trigger_keywords=["天气"])
    robot = SimpleNamespace(id="r1", name="小诺")
    out = await skills.execute_skill(robot, skill, "想看天气", FakeLLM(), session=None)
    assert out is None
