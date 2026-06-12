"""Tests for tool-backed skill execution in the heartbeat path."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import skills
from app.services.llm.base import BaseLLM
from app.services.tools import registry
from app.services.tools.base import Tool, ToolResult


class FakeLLM(BaseLLM):
    def __init__(self, structured=None, text="今天北京晴，18~30度，出门记得防晒～"):
        self.structured = structured or {"city": "北京"}
        self.text = text

    async def generate(self, messages, system_prompt="", temperature=0.7):
        return self.text

    async def generate_structured(self, messages, system_prompt="", schema=None, temperature=0.7):
        return self.structured

    async def embed(self, text):
        return [0.0]


@pytest.fixture(autouse=True)
def fake_tools(monkeypatch):
    saved = dict(registry._TOOLS)
    registry._TOOLS.clear()

    async def _exec(params: dict) -> ToolResult:
        return ToolResult(ok=True, summary="北京：晴，18~30°C")

    registry.register(Tool(
        name="weather", display_name="天气查询", description="查天气",
        trigger_hints=["天气"], params_schema={"city": "城市"}, execute=_exec,
    ))
    monkeypatch.setattr(skills, "_bump_usage", AsyncMock())
    yield
    registry._TOOLS.clear()
    registry._TOOLS.update(saved)


def _robot():
    return SimpleNamespace(id="r1", name="小诺")


def _tool_skill(tool_name="weather"):
    return SimpleNamespace(
        id="s1", name="天气查询", description="查天气",
        execution_prompt=None, tool_name=tool_name, trigger_keywords=["天气"],
    )


@pytest.mark.asyncio
async def test_tool_skill_routes_to_registry():
    output = await skills.execute_skill(
        _robot(), _tool_skill(), "今天好像要降温，想看看天气", FakeLLM(), session=None
    )
    assert output is not None
    assert "晴" in output or "防晒" in output  # 用了 FakeLLM 包装后的人设输出


@pytest.mark.asyncio
async def test_tool_skill_unknown_tool_returns_none():
    output = await skills.execute_skill(
        _robot(), _tool_skill(tool_name="not_registered"), "随便想想", FakeLLM(), session=None
    )
    assert output is None


@pytest.mark.asyncio
async def test_tool_skill_api_failure_returns_none():
    async def fail_exec(params: dict) -> ToolResult:
        return ToolResult(ok=False, error="boom")

    registry._TOOLS["weather"].execute = fail_exec
    output = await skills.execute_skill(
        _robot(), _tool_skill(), "想看看天气", FakeLLM(), session=None
    )
    assert output is None  # 心跳里失败就静默跳过，不输出编造内容


@pytest.mark.asyncio
async def test_plain_skill_still_works():
    plain = SimpleNamespace(
        id="s2", name="讲冷笑话", description="我很会讲冷笑话",
        execution_prompt="用一句话讲个冷笑话", tool_name=None, trigger_keywords=["冷笑话"],
    )
    output = await skills.execute_skill(
        _robot(), plain, "气氛有点僵", FakeLLM(text="冷笑话来了"), session=None
    )
    assert output == "冷笑话来了"
