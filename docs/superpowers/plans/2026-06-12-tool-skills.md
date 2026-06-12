# 工具技能系统实现计划（Tool Skills）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给角色接入真实外部 API 技能（高德美食/路线/天气、新闻热搜、股票/币价/汇率），聊天和心跳两条路径共用一个工具注册表。

**Architecture:** 两段式路由——聊天消息先过关键词门控，再由 DeepSeek flash 输出 `{tool, params}` JSON，注册表执行真实 API 后把结果注入角色回复 prompt；心跳路径通过 `RobotSkill.tool_name` 新字段把内置工具技能挂进现有 trigger_keywords / `execute_skill()` 机制，事件流与前端零改动。

**Tech Stack:** FastAPI + SQLAlchemy(async) + Alembic；HTTP 用项目已有的 `httpx==0.28.1`（spec 中提到的 aiohttp 改用 httpx，不加新依赖）；快模型 `DeepSeekLLM(model="deepseek-v4-flash")`；新闻复用 `claude -p --allowedTools WebSearch` 子进程模式。

**Spec:** `docs/superpowers/specs/2026-06-12-tool-skills-design.md`

**约定：**
- 所有命令在 `backend/` 下执行；测试命令 `python -m pytest tests/<file> -v`
- 开始前切新分支：`git checkout main && git checkout -b feature/tool-skills`
- 计划中的 commit 步骤都在该 feature 分支上，不推送、不合并（合并由用户决定）

---

### Task 1: 工具基础类型与注册表

**Files:**
- Create: `backend/app/services/tools/__init__.py`
- Create: `backend/app/services/tools/base.py`
- Create: `backend/app/services/tools/registry.py`
- Test: `backend/tests/test_tools_registry.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_tools_registry.py
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
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_tools_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.tools'`

- [ ] **Step 3: 实现 base.py 与 registry.py**

```python
# backend/app/services/tools/base.py
"""Tool skills — real external-API-backed skills shared by chat and heartbeat paths."""

from dataclasses import dataclass
from typing import Awaitable, Callable


@dataclass
class ToolResult:
    ok: bool
    summary: str = ""          # 给 LLM 的文字摘要（注入角色回复 prompt）
    data: dict | None = None   # 结构化原始数据（日志/调试用）
    error: str | None = None


@dataclass
class Tool:
    name: str                  # 机器名，如 "food_search"
    display_name: str          # 展示名，如 "美食搜索"
    description: str           # 给路由 LLM 的功能描述
    trigger_hints: list[str]   # 聊天门控关键词；也是心跳技能的 trigger_keywords 种子
    params_schema: dict        # 参数名 -> 中文说明（用于生成路由 prompt）
    execute: Callable[[dict], Awaitable["ToolResult"]]
    timeout: int = 10          # 执行超时秒数（claude CLI 类工具需调大）
```

```python
# backend/app/services/tools/registry.py
"""Central registry: chat router and heartbeat skills both resolve tools here."""

from app.services.tools.base import Tool

_TOOLS: dict[str, Tool] = {}


def register(tool: Tool) -> Tool:
    _TOOLS[tool.name] = tool
    return tool


def get_tool(name: str) -> Tool | None:
    return _TOOLS.get(name)


def all_tools() -> list[Tool]:
    return list(_TOOLS.values())


def gate_match(text: str) -> bool:
    """Cheap keyword gate so we don't pay a router-LLM call for every message."""
    if not text:
        return False
    return any(hint in text for tool in _TOOLS.values() for hint in tool.trigger_hints)
```

```python
# backend/app/services/tools/__init__.py
"""Import this package to trigger tool registration side-effects."""

from app.services.tools.registry import all_tools, gate_match, get_tool, register  # noqa: F401
```

注意：`amap/news/finance` 的 import 在后续任务里逐个加进 `__init__.py`。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_tools_registry.py -v`
Expected: 4 passed（若报 asyncio 标记错误，确认 `pytest-asyncio` 已安装且与 `tests/test_llm.py` 等现有异步测试同样的运行方式；项目已有异步测试，配置应已就绪）

- [ ] **Step 5: Commit**

```bash
git add app/services/tools/ tests/test_tools_registry.py
git commit -m "feat(tools): tool base types and registry for API-backed skills"
```

---

### Task 2: 配置项 + 高德天气工具

**Files:**
- Modify: `backend/app/config.py`
- Create: `backend/app/services/tools/amap.py`
- Modify: `backend/app/services/tools/__init__.py`
- Test: `backend/tests/test_tools_amap.py`

- [ ] **Step 1: 加配置（无需测试，跟随现有模式）**

在 `backend/app/config.py` 的 `Settings` 中 `deepseek_api_key` 行后追加：

```python
    amap_api_key: str = ""       # 高德开放平台 Web 服务 Key
    default_city: str = "北京"    # 工具技能的默认城市（用户聊天中提到地点时覆盖）
```

- [ ] **Step 2: 写失败测试（天气）**

```python
# backend/tests/test_tools_amap.py
"""Tests for amap tools — HTTP layer mocked via monkeypatch on _amap_get."""

import pytest

from app.services.tools import amap


@pytest.fixture(autouse=True)
def fake_key(monkeypatch):
    monkeypatch.setattr("app.config.settings.amap_api_key", "test-key")
    monkeypatch.setattr("app.config.settings.default_city", "北京")


WEATHER_OK = {
    "status": "1",
    "forecasts": [{
        "city": "北京市",
        "casts": [
            {"date": "2026-06-12", "dayweather": "晴", "daytemp": "30", "nighttemp": "18",
             "daywind": "南", "daypower": "≤3"},
            {"date": "2026-06-13", "dayweather": "多云", "daytemp": "28", "nighttemp": "17",
             "daywind": "南", "daypower": "≤3"},
        ],
    }],
}


@pytest.mark.asyncio
async def test_weather_success(monkeypatch):
    async def fake_get(path, params):
        assert path == "/weather/weatherInfo"
        assert params["city"] == "北京"
        return WEATHER_OK

    monkeypatch.setattr(amap, "_amap_get", fake_get)
    result = await amap.weather_tool.execute({"city": "北京"})
    assert result.ok is True
    assert "北京市" in result.summary
    assert "晴" in result.summary


@pytest.mark.asyncio
async def test_weather_uses_default_city(monkeypatch):
    seen = {}

    async def fake_get(path, params):
        seen["city"] = params["city"]
        return WEATHER_OK

    monkeypatch.setattr(amap, "_amap_get", fake_get)
    result = await amap.weather_tool.execute({"city": ""})
    assert seen["city"] == "北京"
    assert result.ok is True


@pytest.mark.asyncio
async def test_weather_city_not_found(monkeypatch):
    async def fake_get(path, params):
        if path == "/weather/weatherInfo":
            return {"status": "1", "forecasts": []}
        if path == "/config/district":
            return {"districts": []}
        raise AssertionError(path)

    monkeypatch.setattr(amap, "_amap_get", fake_get)
    result = await amap.weather_tool.execute({"city": "不存在的城市"})
    assert result.ok is False
    assert result.error


@pytest.mark.asyncio
async def test_weather_no_api_key(monkeypatch):
    monkeypatch.setattr("app.config.settings.amap_api_key", "")
    result = await amap.weather_tool.execute({"city": "北京"})
    assert result.ok is False
    assert "Key" in result.error
```

- [ ] **Step 3: 运行确认失败**

Run: `python -m pytest tests/test_tools_amap.py -v`
Expected: FAIL — `cannot import name 'amap'`

- [ ] **Step 4: 实现 amap.py（天气部分）**

```python
# backend/app/services/tools/amap.py
"""Amap (高德) tools: weather / food_search / route_plan — one free API key covers all."""

import httpx

from app.config import settings
from app.services.tools.base import Tool, ToolResult
from app.services.tools.registry import register

_AMAP_BASE = "https://restapi.amap.com/v3"


async def _amap_get(path: str, params: dict) -> dict:
    params = {**params, "key": settings.amap_api_key}
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{_AMAP_BASE}{path}", params=params)
        resp.raise_for_status()
        return resp.json()


async def _resolve_adcode(city: str) -> str | None:
    data = await _amap_get("/config/district", {"keywords": city, "subdistrict": 0})
    districts = data.get("districts") or []
    return districts[0].get("adcode") if districts else None


async def _weather_execute(params: dict) -> ToolResult:
    if not settings.amap_api_key:
        return ToolResult(ok=False, error="未配置高德 API Key（NOMI_AMAP_API_KEY）")
    city = (params.get("city") or "").strip() or settings.default_city
    try:
        data = await _amap_get("/weather/weatherInfo", {"city": city, "extensions": "all"})
        forecasts = data.get("forecasts") or []
        if not forecasts:
            # 城市名不被天气接口识别时，先解析 adcode 再查一次
            adcode = await _resolve_adcode(city)
            if not adcode:
                return ToolResult(ok=False, error=f"找不到城市「{city}」")
            data = await _amap_get("/weather/weatherInfo", {"city": adcode, "extensions": "all"})
            forecasts = data.get("forecasts") or []
            if not forecasts:
                return ToolResult(ok=False, error=f"查不到「{city}」的天气")
        forecast = forecasts[0]
        casts = forecast.get("casts") or []
        if not casts:
            return ToolResult(ok=False, error="天气数据为空")
        lines = [f"{forecast.get('city', city)}未来天气："]
        for c in casts[:3]:
            lines.append(
                f"{c.get('date')}：白天{c.get('dayweather')}，"
                f"{c.get('nighttemp')}~{c.get('daytemp')}°C，"
                f"{c.get('daywind')}风{c.get('daypower')}级"
            )
        return ToolResult(ok=True, summary="\n".join(lines), data=forecast)
    except Exception as e:
        return ToolResult(ok=False, error=f"天气查询失败：{e}")


weather_tool = register(Tool(
    name="weather",
    display_name="天气查询",
    description="查询中国城市的当天和未来三天天气预报",
    trigger_hints=["天气", "下雨", "下雪", "降温", "气温", "温度", "台风", "雾霾"],
    params_schema={"city": "城市名，用户没提地点就留空字符串"},
    execute=_weather_execute,
))
```

并把 `backend/app/services/tools/__init__.py` 改为：

```python
"""Import this package to trigger tool registration side-effects."""

from app.services.tools import amap  # noqa: F401
from app.services.tools.registry import all_tools, gate_match, get_tool, register  # noqa: F401
```

- [ ] **Step 5: 运行确认通过**

Run: `python -m pytest tests/test_tools_amap.py tests/test_tools_registry.py -v`
Expected: 全部 passed（registry 测试的 autouse fixture 会隔离 amap 注册的真实工具）

- [ ] **Step 6: Commit**

```bash
git add app/config.py app/services/tools/ tests/test_tools_amap.py
git commit -m "feat(tools): amap weather tool with adcode fallback"
```

---

### Task 3: 高德美食搜索 + 路线规划

**Files:**
- Modify: `backend/app/services/tools/amap.py`
- Test: `backend/tests/test_tools_amap.py`（追加）

- [ ] **Step 1: 追加失败测试**

在 `backend/tests/test_tools_amap.py` 末尾追加：

```python
POI_OK = {
    "status": "1",
    "pois": [
        {"name": "海底捞(王府井店)", "address": "王府井大街88号", "biz_ext": {"rating": "4.8"}},
        {"name": "小龙坎火锅", "address": "东直门内大街277号", "biz_ext": {"rating": "4.5"}},
    ],
}


@pytest.mark.asyncio
async def test_food_search_success(monkeypatch):
    async def fake_get(path, params):
        assert path == "/place/text"
        assert params["keywords"] == "火锅"
        assert params["city"] == "北京"
        return POI_OK

    monkeypatch.setattr(amap, "_amap_get", fake_get)
    result = await amap.food_search_tool.execute({"keyword": "火锅", "city": "北京"})
    assert result.ok is True
    assert "海底捞" in result.summary
    assert "4.8" in result.summary


@pytest.mark.asyncio
async def test_food_search_empty(monkeypatch):
    async def fake_get(path, params):
        return {"status": "1", "pois": []}

    monkeypatch.setattr(amap, "_amap_get", fake_get)
    result = await amap.food_search_tool.execute({"keyword": "火星菜", "city": "北京"})
    assert result.ok is False


@pytest.mark.asyncio
async def test_route_plan_success(monkeypatch):
    async def fake_get(path, params):
        if path == "/geocode/geo":
            return {"geocodes": [{"location": "116.40,39.90"}]}
        if path == "/direction/driving":
            return {"route": {"paths": [{"distance": "15000", "duration": "1800"}]}}
        raise AssertionError(path)

    monkeypatch.setattr(amap, "_amap_get", fake_get)
    result = await amap.route_plan_tool.execute(
        {"origin": "国贸", "destination": "西二旗", "city": "北京"}
    )
    assert result.ok is True
    assert "15.0 公里" in result.summary
    assert "30 分钟" in result.summary


@pytest.mark.asyncio
async def test_route_plan_geocode_fail(monkeypatch):
    async def fake_get(path, params):
        return {"geocodes": []}

    monkeypatch.setattr(amap, "_amap_get", fake_get)
    result = await amap.route_plan_tool.execute(
        {"origin": "不存在的地方", "destination": "西二旗", "city": "北京"}
    )
    assert result.ok is False
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_tools_amap.py -v`
Expected: 新增 4 个 FAIL — `module 'app.services.tools.amap' has no attribute 'food_search_tool'`

- [ ] **Step 3: 实现两个工具**

在 `backend/app/services/tools/amap.py` 末尾追加：

```python
async def _food_search_execute(params: dict) -> ToolResult:
    if not settings.amap_api_key:
        return ToolResult(ok=False, error="未配置高德 API Key（NOMI_AMAP_API_KEY）")
    keyword = (params.get("keyword") or "").strip() or "美食"
    city = (params.get("city") or "").strip() or settings.default_city
    try:
        data = await _amap_get("/place/text", {
            "keywords": keyword,
            "city": city,
            "types": "050000",  # 餐饮服务大类
            "offset": 5,
            "page": 1,
            "extensions": "all",
        })
        pois = data.get("pois") or []
        if not pois:
            return ToolResult(ok=False, error=f"在{city}没找到「{keyword}」相关的店")
        lines = [f"在{city}找到这些「{keyword}」相关的店："]
        for p in pois[:5]:
            rating = (p.get("biz_ext") or {}).get("rating") or "暂无评分"
            lines.append(f"- {p.get('name')}（{p.get('address')}，评分 {rating}）")
        return ToolResult(ok=True, summary="\n".join(lines), data={"pois": pois[:5]})
    except Exception as e:
        return ToolResult(ok=False, error=f"美食搜索失败：{e}")


food_search_tool = register(Tool(
    name="food_search",
    display_name="美食搜索",
    description="搜索某个城市的餐厅、美食、小吃等餐饮场所，返回店名、地址和评分",
    trigger_hints=["好吃的", "餐厅", "美食", "吃什么", "饭店", "火锅", "外卖", "小吃", "附近有什么吃"],
    params_schema={
        "keyword": "美食关键词，如「火锅」「日料」「烤鸭」",
        "city": "城市名，用户没提地点就留空字符串",
    },
    execute=_food_search_execute,
))


async def _route_plan_execute(params: dict) -> ToolResult:
    if not settings.amap_api_key:
        return ToolResult(ok=False, error="未配置高德 API Key（NOMI_AMAP_API_KEY）")
    origin_addr = (params.get("origin") or "").strip()
    dest_addr = (params.get("destination") or "").strip()
    city = (params.get("city") or "").strip() or settings.default_city
    if not origin_addr or not dest_addr:
        return ToolResult(ok=False, error="路线规划需要起点和终点")
    try:
        async def geocode(address: str) -> str | None:
            data = await _amap_get("/geocode/geo", {"address": address, "city": city})
            geocodes = data.get("geocodes") or []
            return geocodes[0].get("location") if geocodes else None

        origin = await geocode(origin_addr)
        if not origin:
            return ToolResult(ok=False, error=f"找不到地点「{origin_addr}」")
        dest = await geocode(dest_addr)
        if not dest:
            return ToolResult(ok=False, error=f"找不到地点「{dest_addr}」")

        data = await _amap_get("/direction/driving", {"origin": origin, "destination": dest})
        paths = (data.get("route") or {}).get("paths") or []
        if not paths:
            return ToolResult(ok=False, error="没规划出路线")
        path = paths[0]
        distance_km = int(path.get("distance", 0)) / 1000
        duration_min = int(path.get("duration", 0)) // 60
        summary = (
            f"从{origin_addr}开车到{dest_addr}约 {distance_km:.1f} 公里，"
            f"预计 {duration_min} 分钟。"
        )
        return ToolResult(ok=True, summary=summary,
                          data={"distance_km": distance_km, "duration_min": duration_min})
    except Exception as e:
        return ToolResult(ok=False, error=f"路线规划失败：{e}")


route_plan_tool = register(Tool(
    name="route_plan",
    display_name="路线规划",
    description="规划两地之间的驾车路线，返回距离和预计耗时",
    trigger_hints=["怎么走", "路线", "怎么去", "多远", "导航", "开车去", "要多久"],
    params_schema={
        "origin": "起点地名",
        "destination": "终点地名",
        "city": "城市名，用户没提就留空字符串",
    },
    execute=_route_plan_execute,
))
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_tools_amap.py -v`
Expected: 全部 passed

- [ ] **Step 5: Commit**

```bash
git add app/services/tools/amap.py tests/test_tools_amap.py
git commit -m "feat(tools): amap food_search and route_plan tools"
```

---

### Task 4: 新闻热点工具（复用 Claude CLI WebSearch）

**Files:**
- Create: `backend/app/services/tools/news.py`
- Modify: `backend/app/services/tools/__init__.py`
- Test: `backend/tests/test_tools_news.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_tools_news.py
"""Tests for the news tool — claude CLI subprocess mocked."""

import json

import pytest

from app.services.tools import news


@pytest.mark.asyncio
async def test_news_success(monkeypatch):
    cli_payload = {"result": json.dumps({
        "headlines": ["要点一", "要点二", "要点三"],
        "summary": "今天的综合摘要",
    }, ensure_ascii=False)}

    async def fake_run_claude(prompt: str) -> dict | None:
        assert "WebSearch" in prompt
        return json.loads(cli_payload["result"])

    monkeypatch.setattr(news, "_run_claude_search", fake_run_claude)
    result = await news.news_tool.execute({"topic": "AI"})
    assert result.ok is True
    assert "要点一" in result.summary
    assert "综合摘要" in result.summary


@pytest.mark.asyncio
async def test_news_cli_failure(monkeypatch):
    async def fake_run_claude(prompt: str) -> dict | None:
        return None

    monkeypatch.setattr(news, "_run_claude_search", fake_run_claude)
    result = await news.news_tool.execute({"topic": "AI"})
    assert result.ok is False


def test_news_timeout_is_extended():
    assert news.news_tool.timeout >= 90
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_tools_news.py -v`
Expected: FAIL — `cannot import name 'news'`

- [ ] **Step 3: 实现 news.py**

```python
# backend/app/services/tools/news.py
"""News/hot-topics tool — reuses the claude CLI WebSearch subprocess pattern
(see app/services/web_search.py)."""

import asyncio
import json

from app.services.tools.base import Tool, ToolResult
from app.services.tools.registry import register


async def _run_claude_search(prompt: str) -> dict | None:
    """Run claude CLI with WebSearch and parse its JSON result. None on failure."""
    proc = await asyncio.create_subprocess_exec(
        "claude", "-p", prompt,
        "--output-format", "json",
        "--max-turns", "5",
        "--allowedTools", "WebSearch",
        "--permission-mode", "bypassPermissions",
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=90)
    except asyncio.TimeoutError:
        proc.kill()
        return None
    if proc.returncode != 0:
        print(f"[tools.news] Claude CLI failed: {stderr.decode()[:200]}")
        return None
    try:
        output = json.loads(stdout.decode())
        result_text = output.get("result", "").strip()
        if "```json" in result_text:
            result_text = result_text.split("```json", 1)[1].rsplit("```", 1)[0]
        elif "```" in result_text:
            result_text = result_text.split("```", 1)[1].rsplit("```", 1)[0]
        return json.loads(result_text.strip())
    except Exception as e:
        print(f"[tools.news] Parse error: {e}")
        return None


async def _news_execute(params: dict) -> ToolResult:
    topic = (params.get("topic") or "").strip() or "今日热点新闻"
    prompt = f"""请用 WebSearch 搜索「{topic} 最新消息」，阅读结果后只输出以下合法 JSON（不要任何其他文字）：
{{
  "headlines": ["新闻要点1", "新闻要点2", "新闻要点3"],
  "summary": "100字以内的综合摘要"
}}
搜不到就返回 {{"headlines": [], "summary": ""}}"""
    result = await _run_claude_search(prompt)
    if not result or not result.get("summary"):
        return ToolResult(ok=False, error=f"没搜到「{topic}」的新闻")
    headlines = result.get("headlines") or []
    lines = [f"关于「{topic}」的最新消息：", result["summary"]]
    lines += [f"- {h}" for h in headlines[:3]]
    return ToolResult(ok=True, summary="\n".join(lines), data=result)


news_tool = register(Tool(
    name="news",
    display_name="新闻热点",
    description="搜索最新新闻和热点话题，返回要点和摘要",
    trigger_hints=["新闻", "热搜", "热点", "最近发生", "今天有什么事", "时事"],
    params_schema={"topic": "新闻主题关键词，用户没说就留空字符串（默认今日热点）"},
    execute=_news_execute,
    timeout=120,  # claude CLI 子进程慢，外层超时给足
))
```

`__init__.py` 的 import 行改为：

```python
from app.services.tools import amap, news  # noqa: F401
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_tools_news.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add app/services/tools/ tests/test_tools_news.py
git commit -m "feat(tools): news tool via claude CLI WebSearch"
```

---

### Task 5: 行情工具（股票/币价/汇率）

**Files:**
- Create: `backend/app/services/tools/finance.py`
- Modify: `backend/app/services/tools/__init__.py`
- Test: `backend/tests/test_tools_finance.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_tools_finance.py
"""Tests for finance tools — HTTP helpers mocked."""

import pytest

from app.services.tools import finance


@pytest.mark.asyncio
async def test_stock_success(monkeypatch):
    sina_text = 'var hq_str_sh600519="贵州茅台,1700.00,1690.00,1710.50,1720.00,1695.00";'

    async def fake_fetch(symbol: str) -> str:
        assert symbol == "sh600519"
        return sina_text

    monkeypatch.setattr(finance, "_fetch_sina", fake_fetch)
    result = await finance.stock_tool.execute({"symbol": "sh600519"})
    assert result.ok is True
    assert "贵州茅台" in result.summary
    assert "1710.50" in result.summary
    assert "涨" in result.summary  # 1710.50 > 1690.00


@pytest.mark.asyncio
async def test_stock_not_found(monkeypatch):
    async def fake_fetch(symbol: str) -> str:
        return 'var hq_str_sh999999="";'

    monkeypatch.setattr(finance, "_fetch_sina", fake_fetch)
    result = await finance.stock_tool.execute({"symbol": "sh999999"})
    assert result.ok is False


@pytest.mark.asyncio
async def test_stock_missing_symbol():
    result = await finance.stock_tool.execute({})
    assert result.ok is False


@pytest.mark.asyncio
async def test_crypto_success(monkeypatch):
    async def fake_get_json(url: str, params: dict | None = None) -> dict:
        return {"bitcoin": {"usd": 120000, "cny": 860000, "usd_24h_change": 2.5}}

    monkeypatch.setattr(finance, "_get_json", fake_get_json)
    result = await finance.crypto_tool.execute({"coin": "bitcoin"})
    assert result.ok is True
    assert "bitcoin" in result.summary
    assert "涨" in result.summary


@pytest.mark.asyncio
async def test_crypto_unknown_coin(monkeypatch):
    async def fake_get_json(url: str, params: dict | None = None) -> dict:
        return {}

    monkeypatch.setattr(finance, "_get_json", fake_get_json)
    result = await finance.crypto_tool.execute({"coin": "notacoin"})
    assert result.ok is False


@pytest.mark.asyncio
async def test_forex_success(monkeypatch):
    async def fake_get_json(url: str, params: dict | None = None) -> dict:
        assert url.endswith("/USD")
        return {"result": "success", "rates": {"CNY": 7.1234}}

    monkeypatch.setattr(finance, "_get_json", fake_get_json)
    result = await finance.forex_tool.execute({"base": "USD", "target": "CNY"})
    assert result.ok is True
    assert "7.1234" in result.summary
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_tools_finance.py -v`
Expected: FAIL — `cannot import name 'finance'`

- [ ] **Step 3: 实现 finance.py**

```python
# backend/app/services/tools/finance.py
"""Finance tools: A-share quotes (Sina), crypto (CoinGecko), forex (open.er-api.com).
All free endpoints, no API key required."""

import httpx

from app.services.tools.base import Tool, ToolResult
from app.services.tools.registry import register


async def _get_json(url: str, params: dict | None = None) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


async def _fetch_sina(symbol: str) -> str:
    # hq.sinajs.cn 要求 Referer，返回 GB18030 编码文本
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"https://hq.sinajs.cn/list={symbol}",
            headers={"Referer": "https://finance.sina.com.cn"},
        )
        resp.raise_for_status()
        return resp.content.decode("gb18030", errors="replace")


async def _stock_execute(params: dict) -> ToolResult:
    symbol = (params.get("symbol") or "").strip().lower()
    if not symbol:
        return ToolResult(ok=False, error="缺少股票代码")
    try:
        text = await _fetch_sina(symbol)
        payload = text.split('"')[1] if '"' in text else ""
        fields = payload.split(",")
        if len(fields) < 4 or not fields[0]:
            return ToolResult(ok=False, error=f"没查到「{symbol}」的行情")
        name, open_, prev_close, current = fields[0], fields[1], fields[2], fields[3]
        prev = float(prev_close)
        change = (float(current) - prev) / prev * 100 if prev else 0.0
        direction = "涨" if change >= 0 else "跌"
        summary = (
            f"{name}（{symbol}）现价 {current} 元，今开 {open_}，"
            f"较昨收{direction} {abs(change):.2f}%"
        )
        return ToolResult(ok=True, summary=summary,
                          data={"name": name, "current": current, "change_pct": change})
    except Exception as e:
        return ToolResult(ok=False, error=f"股票查询失败：{e}")


stock_tool = register(Tool(
    name="stock_quote",
    display_name="股票行情",
    description="查询A股/港股/美股实时行情。A股代码如 sh600519、sz000001，美股如 gb_aapl",
    trigger_hints=["股票", "股价", "大盘", "茅台", "上证", "涨了", "跌了"],
    params_schema={"symbol": "股票代码：沪市 sh+6位、深市 sz+6位、美股 gb_+小写代码；尽量从用户说的公司名推断代码"},
    execute=_stock_execute,
))


async def _crypto_execute(params: dict) -> ToolResult:
    coin = (params.get("coin") or "").strip().lower() or "bitcoin"
    try:
        data = await _get_json(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": coin, "vs_currencies": "usd,cny", "include_24hr_change": "true"},
        )
        if coin not in data:
            return ToolResult(ok=False, error=f"没查到币种「{coin}」")
        q = data[coin]
        change = q.get("usd_24h_change") or 0.0
        direction = "涨" if change >= 0 else "跌"
        summary = (
            f"{coin} 现价 ${q.get('usd'):,}（约 ¥{q.get('cny'):,}），"
            f"24小时{direction} {abs(change):.1f}%"
        )
        return ToolResult(ok=True, summary=summary, data=q)
    except Exception as e:
        return ToolResult(ok=False, error=f"币价查询失败：{e}")


crypto_tool = register(Tool(
    name="crypto_price",
    display_name="加密货币行情",
    description="查询加密货币价格，coin 用 CoinGecko 的 id，如 bitcoin、ethereum、dogecoin",
    trigger_hints=["比特币", "以太坊", "币价", "BTC", "ETH", "加密货币", "狗狗币"],
    params_schema={"coin": "币种 id（英文小写），如 bitcoin、ethereum；从用户说的币名推断"},
    execute=_crypto_execute,
))


async def _forex_execute(params: dict) -> ToolResult:
    base = (params.get("base") or "").strip().upper() or "USD"
    target = (params.get("target") or "").strip().upper() or "CNY"
    try:
        data = await _get_json(f"https://open.er-api.com/v6/latest/{base}")
        rate = (data.get("rates") or {}).get(target)
        if not rate:
            return ToolResult(ok=False, error=f"没查到 {base}/{target} 的汇率")
        summary = f"当前汇率：1 {base} ≈ {rate:.4f} {target}"
        return ToolResult(ok=True, summary=summary, data={"base": base, "target": target, "rate": rate})
    except Exception as e:
        return ToolResult(ok=False, error=f"汇率查询失败：{e}")


forex_tool = register(Tool(
    name="exchange_rate",
    display_name="汇率查询",
    description="查询两种货币之间的汇率，货币用三位代码如 USD、CNY、JPY、EUR",
    trigger_hints=["汇率", "美元", "日元", "欧元", "换多少", "兑换"],
    params_schema={"base": "源货币三位代码，默认 USD", "target": "目标货币三位代码，默认 CNY"},
    execute=_forex_execute,
))
```

`__init__.py` 的 import 行改为：

```python
from app.services.tools import amap, finance, news  # noqa: F401
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_tools_finance.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add app/services/tools/ tests/test_tools_finance.py
git commit -m "feat(tools): stock/crypto/forex quote tools"
```

---

### Task 6: 意图路由器（门控 + 快模型 JSON 路由 + 执行）

**Files:**
- Create: `backend/app/services/tool_router.py`
- Test: `backend/tests/test_tool_router.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_tool_router.py
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
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_tool_router.py -v`
Expected: FAIL — `cannot import name 'tool_router'`

- [ ] **Step 3: 实现 tool_router.py**

```python
# backend/app/services/tool_router.py
"""Two-stage tool routing for chat: keyword gate -> flash-LLM intent -> execute.

关键设计：区分「查询意图」和「情绪表达」——
"哪里有好吃的火锅" 是查询，"我好想吃火锅啊" 是抒情，后者不触发工具。
"""

import asyncio

from app.services.llm.base import BaseLLM
from app.services.tools import registry
from app.services.tools.base import ToolResult


def _build_router_prompt(user_message: str) -> str:
    tool_lines = []
    for t in registry.all_tools():
        params = "；".join(f"{k}（{v}）" for k, v in t.params_schema.items())
        tool_lines.append(f"- {t.name}：{t.description}。参数：{params}")
    tools_str = "\n".join(tool_lines)
    return f"""你是一个工具路由器。判断用户消息是否需要调用工具获取真实信息。

可用工具：
{tools_str}

判断规则：
1. 只有用户在【请求真实信息】时才调用工具（如"附近有什么好吃的"、"明天天气怎么样"）
2. 情绪表达、闲聊、回忆【不】调用工具（"我好想吃火锅啊"是抒情不是查询）
3. 参数从用户消息里提取；提取不到的留空字符串
4. 不确定就不调用（tool 输出 null）

用户消息：「{user_message}」

只输出合法 JSON，不要其他文字：
{{"tool": "工具名或null", "params": {{"参数名": "值"}}}}"""


async def route_and_execute(
    user_message: str, llm_flash: BaseLLM
) -> tuple[str, ToolResult] | None:
    """Returns (tool display_name, result) if a tool fired, else None.

    Never raises — any failure degrades to None (chat proceeds without tools).
    """
    if not registry.gate_match(user_message):
        return None

    try:
        decision = await llm_flash.generate_structured(
            messages=[{"role": "user", "content": _build_router_prompt(user_message)}],
            system_prompt="你是工具路由器，只输出 JSON。",
            temperature=0.1,
        )
    except Exception as e:
        print(f"[tool_router] Router LLM failed: {e}")
        return None

    tool_name = decision.get("tool") if isinstance(decision, dict) else None
    if not tool_name or str(tool_name).lower() == "null":
        return None
    tool = registry.get_tool(str(tool_name))
    if not tool:
        return None

    params = decision.get("params") or {}
    if not isinstance(params, dict):
        params = {}
    try:
        result = await asyncio.wait_for(tool.execute(params), timeout=tool.timeout)
    except asyncio.TimeoutError:
        result = ToolResult(ok=False, error="查询超时了")
    except Exception as e:
        result = ToolResult(ok=False, error=f"查询失败：{e}")
    return tool.display_name, result
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_tool_router.py -v`
Expected: 6 passed

- [ ] **Step 5: 全量回归**

Run: `python -m pytest tests/ -v --timeout=120 -x -q` （若无 pytest-timeout 则去掉 --timeout）
Expected: 全部 passed（原有测试不受影响）

- [ ] **Step 6: Commit**

```bash
git add app/services/tool_router.py tests/test_tool_router.py
git commit -m "feat(tools): two-stage tool router (gate + flash-LLM intent)"
```

---

### Task 7: 聊天路径接入（conversations.py）

**Files:**
- Modify: `backend/app/api/conversations.py:153-210`（`send_message` 内）

聊天接入是粘合代码，靠 Task 6 的单测 + Task 9 的端到端验证覆盖，本任务不写新单测。

- [ ] **Step 1: 在 send_message 中加工具路由**

在 `conversations.py` 中 `conversation_so_far = [...]`（约 149-152 行）之后、`# All robots respond in PARALLEL` 之前插入：

```python
    # Tool routing: 每条用户消息最多触发一次真实 API 查询，结果共享给所有回复的角色
    tool_context = ""
    try:
        from app.services.tool_router import route_and_execute
        from app.services.llm.deepseek import DeepSeekLLM

        # 路由用快模型；没配 DeepSeek key 时退回当前聊天模型
        router_llm = DeepSeekLLM(model="deepseek-v4-flash") if settings.deepseek_api_key else llm
        routed = await route_and_execute(body.content, router_llm)
        if routed:
            tool_display_name, tool_result = routed
            if tool_result.ok:
                tool_context = (
                    f"\n\n【你刚用「{tool_display_name}」查到的真实信息】\n"
                    f"{tool_result.summary}\n"
                    "回答时只能使用上面查到的信息，不要编造任何其他数据。"
                )
            else:
                tool_context = (
                    f"\n\n【你尝试用「{tool_display_name}」查询，但失败了："
                    f"{tool_result.error}】\n如实告诉用户没查到，不要编造数据。"
                )
    except Exception as e:
        print(f"[conversations] Tool routing error: {e}")
```

文件顶部确认已有 `from app.config import settings`，没有则添加。

- [ ] **Step 2: 把工具结果注入角色回复**

修改 `_generate_reply` 中的 LLM 调用（约 204 行），把：

```python
        content = await llm.generate(
            messages=[{"role": "user", "content": prompt}],
            system_prompt=system,
        )
```

改为：

```python
        content = await llm.generate(
            messages=[{"role": "user", "content": prompt + tool_context}],
            system_prompt=system,
        )
```

- [ ] **Step 3: 语法与回归检查**

Run: `python -c "import app.api.conversations"` && `python -m pytest tests/test_conversations.py -v`
Expected: import 无错；conversations 测试全部 passed

- [ ] **Step 4: Commit**

```bash
git add app/api/conversations.py
git commit -m "feat(chat): inject tool results into robot replies via tool router"
```

---

### Task 8: 心跳路径——tool_name 字段 + execute_skill 路由

**Files:**
- Modify: `backend/app/db/models.py:234-247`（RobotSkill）
- Create: `backend/alembic/versions/<auto>_add_tool_name_to_robot_skills.py`
- Modify: `backend/app/services/skills.py`
- Test: `backend/tests/test_tool_skills.py`

- [ ] **Step 1: 模型加字段**

在 `models.py` 的 `RobotSkill` 类中 `skill_type` 行后添加：

```python
    tool_name: Mapped[str | None] = mapped_column(Text)  # 非空表示这是注册表里的工具技能
```

- [ ] **Step 2: 生成迁移**

Run: `alembic revision -m "add tool_name to robot_skills"`

把生成文件的 upgrade/downgrade 改为：

```python
def upgrade() -> None:
    op.add_column('robot_skills', sa.Column('tool_name', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('robot_skills', 'tool_name')
```

Run: `alembic upgrade head`
Expected: 无错，`robot_skills` 表多出 `tool_name` 列

- [ ] **Step 3: 写失败测试**

```python
# backend/tests/test_tool_skills.py
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
```

- [ ] **Step 4: 运行确认失败**

Run: `python -m pytest tests/test_tool_skills.py -v`
Expected: FAIL — `module 'app.services.skills' has no attribute '_bump_usage'`（及 tool 路由不存在）

- [ ] **Step 5: 改造 skills.py**

文件顶部 import 区添加：

```python
import asyncio
import json
```

把 `execute_skill` 中的 usage 统计抽成共用函数（放在 `execute_skill` 之前）：

```python
async def _bump_usage(session: AsyncSession | None, skill_id) -> None:
    """Update usage stats; tolerates session=None (tests / fire-and-forget paths)."""
    if session is None:
        return
    async with session.begin_nested():
        fresh = (await session.execute(
            select(RobotSkill).where(RobotSkill.id == skill_id)
        )).scalar_one_or_none()
        if fresh:
            fresh.usage_count = (fresh.usage_count or 0) + 1
            fresh.last_used_at = datetime.utcnow()
    await session.commit()
```

`execute_skill` 改为（完整替换原函数）：

```python
async def execute_skill(
    robot: Robot,
    skill: RobotSkill,
    context: str,
    llm: BaseLLM,
    session: AsyncSession,
) -> str | None:
    """Execute a skill given the current context. Returns the output or None."""
    # 工具技能：先取真实数据，再用人设语气包装
    if getattr(skill, "tool_name", None):
        return await _execute_tool_skill(robot, skill, context, llm, session)

    prompt = f"""你是 {robot.name}。此刻你在用「{skill.name}」这项技能。

关于这项技能：{skill.description or ''}
你使用它的方式：{skill.execution_prompt or ''}

当前情境：{context}

现在，自然地展示这项技能。输出应该简短、真实，体现你的个性。不要解释，直接表现。"""

    try:
        result = await llm.generate(
            messages=[{"role": "user", "content": prompt}],
            system_prompt=f"你是 {robot.name}，正在自然地展示一项技能。",
        )
        await _bump_usage(session, skill.id)
        return result.strip() if result else None
    except Exception as e:
        print(f"[skills] Execute failed for {skill.name}: {e}")
        return None


async def _execute_tool_skill(
    robot: Robot,
    skill: RobotSkill,
    context: str,
    llm: BaseLLM,
    session: AsyncSession,
) -> str | None:
    """Tool-backed skill: fetch real data from the registry, wrap in the robot's voice.
    心跳场景里任何失败都静默返回 None——绝不让角色编造数据。"""
    from app.services.tools import registry
    from app.services.tools.base import ToolResult

    tool = registry.get_tool(skill.tool_name)
    if not tool:
        return None

    # 从当前想法中提取工具参数
    try:
        params = await llm.generate_structured(
            messages=[{"role": "user", "content": f"""从下面这段想法中提取调用「{tool.display_name}」需要的参数。
参数说明：{json.dumps(tool.params_schema, ensure_ascii=False)}
想法：「{context}」
提取不到的参数留空字符串。只输出 JSON 对象。"""}],
            system_prompt="提取工具参数，只输出 JSON。",
        )
        if not isinstance(params, dict):
            params = {}
    except Exception:
        params = {}

    try:
        result = await asyncio.wait_for(tool.execute(params), timeout=tool.timeout)
    except Exception as e:
        result = ToolResult(ok=False, error=str(e))
    if not result.ok:
        print(f"[skills] Tool {skill.tool_name} failed: {result.error}")
        return None

    prompt = f"""你是 {robot.name}。你刚用「{skill.name}」查到了真实信息：
{result.summary}

当前情境：{context}

用你的语气，把里面有意思的部分自然地分享出来（2-3句话）。只能用上面查到的信息，不要编造。"""
    try:
        output = await llm.generate(
            messages=[{"role": "user", "content": prompt}],
            system_prompt=f"你是 {robot.name}，正在分享你刚查到的真实信息。",
        )
        await _bump_usage(session, skill.id)
        return output.strip() if output else None
    except Exception as e:
        print(f"[skills] Tool skill voice-wrap failed: {e}")
        return None
```

注意：原 `execute_skill` 里内联的 usage 统计代码删除，统一走 `_bump_usage`。

- [ ] **Step 6: 运行确认通过 + 回归**

Run: `python -m pytest tests/test_tool_skills.py tests/test_models.py -v`
Expected: 全部 passed

- [ ] **Step 7: Commit**

```bash
git add app/db/models.py alembic/versions/ app/services/skills.py tests/test_tool_skills.py
git commit -m "feat(skills): route tool-backed RobotSkills through tool registry in heartbeat path"
```

---

### Task 9: 种子脚本 + .env.example + 端到端验证

**Files:**
- Create: `backend/app/scripts/__init__.py`（若不存在）
- Create: `backend/app/scripts/seed_tool_skills.py`
- Modify: `backend/.env.example`

- [ ] **Step 1: 写种子脚本**

```python
# backend/app/scripts/seed_tool_skills.py
"""Seed built-in tool skills for all robots (idempotent).

Run from backend/: python -m app.scripts.seed_tool_skills
"""

import asyncio

from sqlalchemy import select

import app.services.tools  # noqa: F401 — import side-effect registers tools
from app.db.engine import async_session
from app.db.models import Robot, RobotSkill
from app.services.tools.registry import all_tools


async def seed_tool_skills(session, robot_id) -> int:
    """Insert missing tool skills for one robot. Returns number added."""
    existing = set((await session.execute(
        select(RobotSkill.tool_name)
        .where(RobotSkill.robot_id == robot_id)
        .where(RobotSkill.tool_name.isnot(None))
    )).scalars().all())

    added = 0
    for tool in all_tools():
        if tool.name in existing:
            continue
        session.add(RobotSkill(
            robot_id=robot_id,
            name=tool.display_name,
            description=tool.description,
            trigger_keywords=tool.trigger_hints,
            execution_prompt=None,
            skill_type="tool",
            tool_name=tool.name,
            usage_count=0,
        ))
        added += 1
    await session.commit()
    return added


async def main():
    async with async_session() as session:
        robots = (await session.execute(select(Robot))).scalars().all()
        for robot in robots:
            n = await seed_tool_skills(session, robot.id)
            print(f"{robot.name}: +{n} tool skills")


if __name__ == "__main__":
    asyncio.run(main())
```

若 `backend/app/scripts/` 不存在则创建并加空 `__init__.py`。

- [ ] **Step 2: 更新 .env.example**

在 `backend/.env.example` 末尾追加：

```bash
# Tool skills（工具技能）
NOMI_AMAP_API_KEY=        # 高德开放平台 Web 服务 Key：https://console.amap.com/dev/key/app
NOMI_DEFAULT_CITY=北京     # 美食/路线/天气的默认城市
```

- [ ] **Step 3: 运行种子脚本**

Run: `python -m app.scripts.seed_tool_skills`
Expected: 每个角色输出 `+7 tool skills`（weather、food_search、route_plan、news、stock_quote、crypto_price、exchange_rate）；重跑一次输出 `+0`（幂等）

- [ ] **Step 4: 全量回归**

Run: `python -m pytest tests/ -q`
Expected: 全部 passed

- [ ] **Step 5: 端到端手测（需要真实 NOMI_AMAP_API_KEY 已配置、后端已启动）**

```bash
# 1. 天气（聊天路径）
curl -s -X POST "http://localhost:8100/api/conversations" | jq -r .id  # 拿 conversation_id
curl -s -X POST "http://localhost:8100/api/conversations/<id>/message" \
  -H "Content-Type: application/json" \
  -d '{"content": "北京明天天气怎么样？"}' | jq '.messages[-1].content'
# Expected: 回复包含真实温度/天气描述

# 2. 美食
curl -s -X POST "http://localhost:8100/api/conversations/<id>/message" \
  -H "Content-Type: application/json" \
  -d '{"content": "帮我找找北京哪里有好吃的火锅"}' | jq '.messages[-1].content'
# Expected: 回复包含真实店名和地址

# 3. 负例（抒情不触发）
curl -s -X POST "http://localhost:8100/api/conversations/<id>/message" \
  -H "Content-Type: application/json" \
  -d '{"content": "我好想吃火锅啊，心情不好"}' | jq '.messages[-1].content'
# Expected: 正常情感回应，不包含店名列表（看后端日志确认 tool 未触发或路由判 null）

# 4. 心跳路径：admin 面板技能 tab 应显示 skill_type=tool 的新技能；
#    等待心跳中角色想法命中触发词后，群聊出现 ⚡ skill_used 真实数据分享
```

- [ ] **Step 6: Commit**

```bash
git add app/scripts/ .env.example
git commit -m "feat(tools): seed script for built-in tool skills + env example"
```

---

## 自检记录（spec 覆盖）

| Spec 要求 | 任务 |
|-----------|------|
| 工具注册表 base/registry | Task 1 |
| 高德三件套 | Task 2、3 |
| 新闻（claude CLI 模式） | Task 4 |
| 行情三接口 | Task 5 |
| 关键词门控 + 意图路由 + 超时 + 防编造 | Task 6 |
| 聊天注入 | Task 7 |
| migration + execute_skill 路由 + 事件流不变 | Task 8 |
| 种子 + 配置 + 测试 + E2E | Task 9 |

已知偏离 spec：HTTP 库用 httpx（项目现有依赖）而非 aiohttp；天气接口加了 adcode 兜底解析（高德 weatherInfo 对城市名支持不稳）。
