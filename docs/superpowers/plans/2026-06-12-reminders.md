# 提醒/闹钟 + 工具开关 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 聊天里设提醒（"明早八点叫我"），到点角色主动喊人（复用 message 事件，前端零改动）；所有工具技能可在 admin 面板运行时开关。

**Architecture:** 提醒 = 3 个新工具（set/list/cancel，`autonomous=False` 不进心跳种子）；核心逻辑在 `services/reminders.py`（可单测），触发循环由 FastAPI lifespan 启动（独立于 heartbeat 睡眠状态）；工具开关 = `tool_settings` 表 + registry 内存缓存 + admin API + admin_panel.html 模态 UI。

**Tech Stack:** 既有栈。时区用 `zoneinfo`（新配置 `NOMI_TIMEZONE=Asia/Shanghai`），DB 存 UTC naive（库内惯例）。

**Spec:** `docs/superpowers/specs/2026-06-12-reminders-design.md`

**约定：** 命令在 `backend/` 下执行；测试 `.venv/bin/python -m pytest tests/<file> -v`；**直接在 main 分支工作（用户约定，不开分支）**；commit message 结尾加 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`。

---

### Task 1: 数据模型 + 迁移（Reminder / ToolSetting）

**Files:** Modify `backend/app/db/models.py`、`backend/tests/test_models.py`；Create migration

- [ ] **Step 1**: `models.py` 文件顶部 import 区确认有 `Boolean`（`from sqlalchemy import ...` 行，没有就加）。在 `RobotSkill` 类之后添加：

```python
class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    robot_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("robots.id"))  # 空=触发时随机选角色
    title: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False)  # UTC naive
    repeat: Mapped[str] = mapped_column(Text, default="once")  # 'once' | 'daily'
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_triggered_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)


class ToolSetting(Base):
    __tablename__ = "tool_settings"

    tool_name: Mapped[str] = mapped_column(Text, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow
    )
```

- [ ] **Step 2**: `tests/test_models.py` 的 expected 集合加 `"reminders", "tool_settings"`，跑 `python -m pytest tests/test_models.py -v` 确认通过
- [ ] **Step 3**: `alembic revision -m "add reminders and tool_settings tables"`，upgrade/downgrade 写两张表的 create/drop（字段同模型，reminders.robot_id 加 FK robots.id）；`alembic upgrade head` 成功且 `alembic current` 为新 head
- [ ] **Step 4**: Commit `feat(db): reminders and tool_settings tables`

---

### Task 2: 工具开关机制（registry 缓存 + admin API + 路由/心跳过滤）

**Files:** Modify `app/services/tools/registry.py`、`app/services/tool_router.py`、`app/services/skills.py`、`app/api/admin.py`、`app/main.py`；Create `app/services/tools/toggles.py`；Test `tests/test_tool_toggles.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_tool_toggles.py
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
```

- [ ] **Step 2**: 运行确认失败（`_disabled` 不存在）
- [ ] **Step 3**: `registry.py` 添加（保持现有函数不动，`gate_match`/新增函数改为过滤禁用）：

```python
_disabled: set[str] = set()


def is_enabled(name: str) -> bool:
    return name not in _disabled


def set_tool_state(name: str, enabled: bool) -> None:
    if enabled:
        _disabled.discard(name)
    else:
        _disabled.add(name)


def set_disabled(names: set[str]) -> None:
    _disabled.clear()
    _disabled.update(names)


def enabled_tools() -> list[Tool]:
    return [t for t in _TOOLS.values() if t.name not in _disabled]
```

并把 `gate_match` 的迭代源从 `_TOOLS.values()` 改为 `enabled_tools()`。

- [ ] **Step 4**: `tool_router.py`：`_build_router_prompt` 中 `registry.all_tools()` 改为 `registry.enabled_tools()`；执行前的 `tool = registry.get_tool(...)` 后追加 `if not tool or not registry.is_enabled(tool.name): return None`（替换原 `if not tool`）。`skills.py` `_execute_tool_skill` 中 `tool = registry.get_tool(skill.tool_name)` 后的判断改为 `if not tool or not registry.is_enabled(skill.tool_name): return None`
- [ ] **Step 5**: Create `app/services/tools/toggles.py`：

```python
"""DB-backed tool enable/disable, hydrated into the in-memory registry."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ToolSetting
from app.services.tools import registry


async def hydrate_tool_settings() -> None:
    """Load disabled set from DB into registry. Call once at app startup."""
    from app.db.engine import async_session
    try:
        async with async_session() as session:
            rows = (await session.execute(
                select(ToolSetting.tool_name).where(ToolSetting.enabled.is_(False))
            )).scalars().all()
            registry.set_disabled(set(rows))
            if rows:
                print(f"[tools] Disabled tools loaded: {sorted(rows)}")
    except Exception as e:
        print(f"[tools] Hydrate tool settings failed (non-fatal): {e}")


async def set_tool_enabled(session: AsyncSession, tool_name: str, enabled: bool) -> None:
    """Upsert DB row and update in-memory state."""
    row = (await session.execute(
        select(ToolSetting).where(ToolSetting.tool_name == tool_name)
    )).scalar_one_or_none()
    if row:
        row.enabled = enabled
        row.updated_at = datetime.utcnow()
    else:
        session.add(ToolSetting(tool_name=tool_name, enabled=enabled))
    await session.commit()
    registry.set_tool_state(tool_name, enabled)
```

- [ ] **Step 6**: `app/api/admin.py` 末尾添加：

```python
@router.get("/tools")
async def list_tool_settings():
    """All registered tools with their enabled state."""
    import app.services.tools  # noqa: F401 — ensure registration
    from app.services.tools.registry import all_tools, is_enabled
    return [
        {"name": t.name, "display_name": t.display_name,
         "description": t.description, "enabled": is_enabled(t.name)}
        for t in all_tools()
    ]


@router.put("/tools/{tool_name}")
async def update_tool_setting(tool_name: str, body: dict, session: AsyncSession = Depends(get_session)):
    import app.services.tools  # noqa: F401
    from app.services.tools.registry import get_tool
    from app.services.tools.toggles import set_tool_enabled
    if not get_tool(tool_name):
        raise HTTPException(status_code=404, detail=f"Unknown tool: {tool_name}")
    enabled = bool(body.get("enabled", True))
    await set_tool_enabled(session, tool_name, enabled)
    return {"name": tool_name, "enabled": enabled}
```

（确认 admin.py 顶部已有 `Depends/get_session/HTTPException/AsyncSession` import，缺哪个补哪个。）

- [ ] **Step 7**: `app/main.py` lifespan 的 `yield` 之前加：

```python
    from app.services.tools.toggles import hydrate_tool_settings
    await hydrate_tool_settings()
```

- [ ] **Step 8**: `python -m pytest tests/test_tool_toggles.py tests/test_tool_router.py tests/test_tools_registry.py -v` 全过；`python -c "import app.main"` 无错
- [ ] **Step 9**: Commit `feat(tools): runtime tool toggles (registry cache + tool_settings table + admin API)`

---

### Task 3: 提醒核心服务 services/reminders.py

**Files:** Modify `app/config.py`；Create `app/services/reminders.py`；Test `tests/test_reminders_service.py`

- [ ] **Step 1**: `config.py` Settings 加 `timezone: str = "Asia/Shanghai"  # 提醒/时间解析时区`
- [ ] **Step 2: 写失败测试**

```python
# backend/tests/test_reminders_service.py
"""Tests for reminder core logic on in-memory sqlite."""

from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Base, Reminder
from app.services import reminders as svc


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


def test_local_utc_roundtrip():
    # Asia/Shanghai = UTC+8
    utc = svc.local_to_utc("2026-06-13 08:00")
    assert utc == datetime(2026, 6, 13, 0, 0)
    assert svc.to_local_str(utc) == "2026-06-13 08:00"


def test_local_to_utc_invalid():
    assert svc.local_to_utc("明天早上") is None


@pytest.mark.asyncio
async def test_create_and_find_due(session):
    r = await svc.create_reminder(session, "起床", "2026-06-13 08:00", "once")
    assert r is not None and r.is_active

    not_yet = await svc.find_due(session, datetime(2026, 6, 12, 23, 0))
    assert not_yet == []
    due = await svc.find_due(session, datetime(2026, 6, 13, 0, 1))
    assert len(due) == 1 and due[0].title == "起床"


@pytest.mark.asyncio
async def test_advance_once_deactivates(session):
    r = await svc.create_reminder(session, "开会", "2026-06-13 08:00", "once")
    await svc.advance_after_trigger(session, r, datetime(2026, 6, 13, 0, 1))
    assert r.is_active is False and r.last_triggered_at is not None


@pytest.mark.asyncio
async def test_advance_daily_moves_to_future(session):
    r = await svc.create_reminder(session, "吃药", "2026-06-13 08:00", "daily")
    # 错过两天后才触发：应直接推进到未来，而不是连补两次
    await svc.advance_after_trigger(session, r, datetime(2026, 6, 15, 0, 1))
    assert r.is_active is True
    assert r.trigger_time > datetime(2026, 6, 15, 0, 1)
    assert r.trigger_time.hour == 0  # 仍是本地 08:00（UTC 00:00）


@pytest.mark.asyncio
async def test_cancel_by_keyword(session):
    await svc.create_reminder(session, "提醒喝水", "2026-06-13 08:00", "once")
    await svc.create_reminder(session, "提醒吃饭", "2026-06-13 09:00", "once")

    n, matches = await svc.cancel_by_keyword(session, "喝水")
    assert n == 1
    n2, matches2 = await svc.cancel_by_keyword(session, "提醒")  # 只剩吃饭一条
    assert n2 == 1
    n3, _ = await svc.cancel_by_keyword(session, "不存在")
    assert n3 == 0


@pytest.mark.asyncio
async def test_cancel_ambiguous_cancels_nothing(session):
    await svc.create_reminder(session, "喝水一", "2026-06-13 08:00", "once")
    await svc.create_reminder(session, "喝水二", "2026-06-13 09:00", "once")
    n, matches = await svc.cancel_by_keyword(session, "喝水")
    assert n == 0 and len(matches) == 2  # 歧义不动手，返回候选
```

- [ ] **Step 3**: 运行确认失败。若缺 `aiosqlite` 或 `pytest_asyncio` fixture 装饰器报错，先 `.venv/bin/pip install aiosqlite pytest-asyncio` 已装则跳过（项目 sqlite 模式已支持，大概率已有）
- [ ] **Step 4**: 实现 `app/services/reminders.py`：

```python
"""Reminder core logic — creation, due-scan, repeat advance, cancellation.

时间约定：DB 存 UTC naive（库内惯例）；用户口径是 settings.timezone 本地时间。
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import Reminder

_FMT = "%Y-%m-%d %H:%M"


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.timezone)


def local_to_utc(local_str: str) -> datetime | None:
    """'2026-06-13 08:00'（本地）→ UTC naive；解析失败返回 None。"""
    try:
        local = datetime.strptime(local_str.strip(), _FMT).replace(tzinfo=_tz())
        return local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    except Exception:
        return None


def to_local_str(utc_naive: datetime) -> str:
    return (utc_naive.replace(tzinfo=ZoneInfo("UTC"))
            .astimezone(_tz()).strftime(_FMT))


def now_local_str() -> str:
    return datetime.now(_tz()).strftime(_FMT)


async def create_reminder(
    session: AsyncSession, title: str, local_time_str: str, repeat: str = "once"
) -> Reminder | None:
    trigger = local_to_utc(local_time_str)
    if not trigger or not title.strip():
        return None
    if repeat not in ("once", "daily"):
        repeat = "once"
    reminder = Reminder(title=title.strip(), trigger_time=trigger, repeat=repeat, is_active=True)
    session.add(reminder)
    await session.commit()
    await session.refresh(reminder)
    return reminder


async def list_active(session: AsyncSession) -> list[Reminder]:
    rows = await session.execute(
        select(Reminder).where(Reminder.is_active.is_(True)).order_by(Reminder.trigger_time)
    )
    return list(rows.scalars().all())


async def find_due(session: AsyncSession, now_utc: datetime) -> list[Reminder]:
    rows = await session.execute(
        select(Reminder)
        .where(Reminder.is_active.is_(True))
        .where(Reminder.trigger_time <= now_utc)
    )
    return list(rows.scalars().all())


async def advance_after_trigger(session: AsyncSession, reminder: Reminder, now_utc: datetime) -> None:
    """once → 失活；daily → 推进到未来的下一个同时刻（错过多天不连环补发）。"""
    reminder.last_triggered_at = now_utc
    if reminder.repeat == "daily":
        next_time = reminder.trigger_time
        while next_time <= now_utc:
            next_time += timedelta(days=1)
        reminder.trigger_time = next_time
    else:
        reminder.is_active = False
    await session.commit()


async def cancel_by_keyword(session: AsyncSession, keyword: str) -> tuple[int, list[Reminder]]:
    """精确命中一条才取消；多条返回候选不动手；返回 (取消数, 匹配列表)。"""
    matches = [r for r in await list_active(session) if keyword.strip() and keyword.strip() in r.title]
    if len(matches) == 1:
        matches[0].is_active = False
        await session.commit()
        return 1, matches
    return 0, matches
```

- [ ] **Step 5**: `python -m pytest tests/test_reminders_service.py -v` 8 个全过
- [ ] **Step 6**: Commit `feat(reminders): core service (create/due-scan/daily-advance/cancel) with sqlite tests`

---

### Task 4: 提醒三工具 + autonomous 标记 + 路由时间注入

**Files:** Modify `app/services/tools/base.py`、`app/services/tool_router.py`、`app/services/tools/__init__.py`、`app/scripts/seed_tool_skills.py`；Create `app/services/tools/reminders.py`；Test `tests/test_tools_reminders.py`

- [ ] **Step 1**: `base.py` 的 Tool 加字段（放 timeout 之后）：`autonomous: bool = True  # False = 不种子进心跳技能（如提醒类，角色不该自己给自己设）`
- [ ] **Step 2: 写失败测试**

```python
# backend/tests/test_tools_reminders.py
"""Tests for reminder tools — service layer mocked."""

from types import SimpleNamespace
from datetime import datetime

import pytest

from app.services.tools import reminders as rtools


@pytest.mark.asyncio
async def test_set_reminder_success(monkeypatch):
    async def fake_create(session, title, time_str, repeat):
        assert title == "起床" and time_str == "2026-06-13 08:00" and repeat == "once"
        return SimpleNamespace(title=title, trigger_time=datetime(2026, 6, 13, 0, 0), repeat=repeat)

    monkeypatch.setattr(rtools, "_create", fake_create)
    result = await rtools.set_reminder_tool.execute(
        {"title": "起床", "time": "2026-06-13 08:00", "repeat": "once"})
    assert result.ok is True
    assert "起床" in result.summary and "08:00" in result.summary


@pytest.mark.asyncio
async def test_set_reminder_bad_time(monkeypatch):
    async def fake_create(session, title, time_str, repeat):
        return None

    monkeypatch.setattr(rtools, "_create", fake_create)
    result = await rtools.set_reminder_tool.execute({"title": "起床", "time": "明天吧"})
    assert result.ok is False


@pytest.mark.asyncio
async def test_list_reminders_empty(monkeypatch):
    async def fake_list(session):
        return []

    monkeypatch.setattr(rtools, "_list", fake_list)
    result = await rtools.list_reminders_tool.execute({})
    assert result.ok is True
    assert "没有" in result.summary


@pytest.mark.asyncio
async def test_cancel_ambiguous(monkeypatch):
    async def fake_cancel(session, kw):
        return 0, [SimpleNamespace(title="喝水一", trigger_time=datetime(2026, 6, 13, 0, 0)),
                   SimpleNamespace(title="喝水二", trigger_time=datetime(2026, 6, 13, 1, 0))]

    monkeypatch.setattr(rtools, "_cancel", fake_cancel)
    result = await rtools.cancel_reminder_tool.execute({"keyword": "喝水"})
    assert result.ok is True
    assert "喝水一" in result.summary  # 列出候选让用户说具体


def test_reminder_tools_not_autonomous():
    assert rtools.set_reminder_tool.autonomous is False
    assert rtools.list_reminders_tool.autonomous is False
    assert rtools.cancel_reminder_tool.autonomous is False
```

- [ ] **Step 3**: 运行确认失败，实现 `app/services/tools/reminders.py`：

```python
"""Reminder tools: set / list / cancel — chat-path only (autonomous=False)."""

from app.services.reminders import (
    cancel_by_keyword as _cancel,
    create_reminder as _create,
    list_active as _list,
    to_local_str,
)
from app.services.tools.base import Tool, ToolResult
from app.services.tools.registry import register


async def _set_execute(params: dict) -> ToolResult:
    title = (params.get("title") or "").strip()
    time_str = (params.get("time") or "").strip()
    repeat = (params.get("repeat") or "once").strip()
    if not title or not time_str:
        return ToolResult(ok=False, error="缺少提醒内容或时间")
    from app.db.engine import async_session
    try:
        async with async_session() as session:
            reminder = await _create(session, title, time_str, repeat)
        if not reminder:
            return ToolResult(ok=False, error=f"没听懂时间「{time_str}」，需要具体的日期和时刻")
        when = to_local_str(reminder.trigger_time)
        rep = "（每天重复）" if reminder.repeat == "daily" else ""
        return ToolResult(ok=True, summary=f"提醒已设好：{when} 提醒「{reminder.title}」{rep}",
                          data={"title": reminder.title, "time": when, "repeat": reminder.repeat})
    except Exception as e:
        return ToolResult(ok=False, error=f"设置提醒失败：{e}")


set_reminder_tool = register(Tool(
    name="set_reminder",
    display_name="设置提醒",
    description="为用户设置定时提醒/闹钟。time 必须换算成具体时刻（格式 YYYY-MM-DD HH:MM，按上面给出的当前时间推算「明天/今晚/半小时后」）",
    trigger_hints=["提醒我", "叫我", "闹钟", "别忘了", "记得提醒", "分钟后", "小时后"],
    params_schema={
        "title": "提醒内容，如「起床」「开会」",
        "time": "触发时刻，YYYY-MM-DD HH:MM（本地时间，按当前时间推算相对表达）",
        "repeat": "once 或 daily（用户说「每天」才用 daily）",
    },
    execute=_set_execute,
    autonomous=False,
))


async def _list_execute(params: dict) -> ToolResult:
    from app.db.engine import async_session
    try:
        async with async_session() as session:
            items = await _list(session)
        if not items:
            return ToolResult(ok=True, summary="当前没有任何提醒")
        lines = ["当前的提醒："]
        for r in items:
            rep = "（每天）" if r.repeat == "daily" else ""
            lines.append(f"- {to_local_str(r.trigger_time)} {r.title}{rep}")
        return ToolResult(ok=True, summary="\n".join(lines))
    except Exception as e:
        return ToolResult(ok=False, error=f"查询提醒失败：{e}")


list_reminders_tool = register(Tool(
    name="list_reminders",
    display_name="查看提醒",
    description="列出用户当前设置的所有提醒",
    trigger_hints=["什么提醒", "哪些提醒", "提醒列表", "设了什么"],
    params_schema={},
    execute=_list_execute,
    autonomous=False,
))


async def _cancel_execute(params: dict) -> ToolResult:
    keyword = (params.get("keyword") or "").strip()
    if not keyword:
        return ToolResult(ok=False, error="要取消哪个提醒？")
    from app.db.engine import async_session
    try:
        async with async_session() as session:
            n, matches = await _cancel(session, keyword)
        if n == 1:
            return ToolResult(ok=True, summary=f"已取消提醒「{matches[0].title}」")
        if len(matches) > 1:
            lines = ["有好几个相关的提醒，说具体点要取消哪个："]
            lines += [f"- {to_local_str(r.trigger_time)} {r.title}" for r in matches]
            return ToolResult(ok=True, summary="\n".join(lines))
        return ToolResult(ok=False, error=f"没找到和「{keyword}」相关的提醒")
    except Exception as e:
        return ToolResult(ok=False, error=f"取消提醒失败：{e}")


cancel_reminder_tool = register(Tool(
    name="cancel_reminder",
    display_name="取消提醒",
    description="按关键词取消用户的某个提醒",
    trigger_hints=["取消提醒", "不用提醒", "删掉提醒", "取消那个"],
    params_schema={"keyword": "提醒内容关键词"},
    execute=_cancel_execute,
    autonomous=False,
))
```

`__init__.py` import 行改为 `from app.services.tools import amap, finance, news, reminders  # noqa: F401`

- [ ] **Step 4**: `tool_router.py` `_build_router_prompt` 的"默认城市"那行之前加一行当前时间（让 LLM 能换算"明早/半小时后"）：

```python
    from app.services.reminders import now_local_str
```
（放函数内部 import，避免循环依赖。）prompt 字符串中"默认城市"前插入：
```
当前时间：{now_local_str()}（{settings.timezone}）

```

- [ ] **Step 5**: `seed_tool_skills.py` 的 for 循环内、`if tool.name in existing` 之前加：

```python
        if not tool.autonomous:
            continue  # 提醒类工具只走聊天路由，不进心跳技能
```

- [ ] **Step 6**: `python -m pytest tests/test_tools_reminders.py tests/test_tool_router.py tests/test_tools_registry.py -v` 全过；运行 `python -m app.scripts.seed_tool_skills` 确认所有角色输出 `+0`（提醒工具被正确跳过）
- [ ] **Step 7**: Commit `feat(tools): set/list/cancel reminder tools + autonomous flag + router time context`

---

### Task 5: 触发循环（lifespan 启动，独立于 heartbeat 睡眠）

**Files:** Modify `app/services/reminders.py`、`app/main.py`；Test `tests/test_reminders_service.py`（追加）

- [ ] **Step 1: 追加失败测试**（`tests/test_reminders_service.py` 末尾）：

```python
@pytest.mark.asyncio
async def test_fire_reminder_emits_and_advances(session, monkeypatch):
    from types import SimpleNamespace

    emitted = []

    async def fake_emit(event):
        emitted.append(event)

    async def fake_save(robot_id, robot_name, content):
        pass

    async def fake_pick(s):
        return SimpleNamespace(id="r1", name="小诺", personality=[])

    class FakeLLM:
        async def generate(self, messages, system_prompt="", temperature=0.7):
            return "主人！该起床啦！"

    monkeypatch.setattr(svc, "_heartbeat_emit", fake_emit)
    monkeypatch.setattr(svc, "_heartbeat_save", fake_save)
    monkeypatch.setattr(svc, "_pick_robot", fake_pick)
    monkeypatch.setattr(svc, "_make_flash_llm", lambda: FakeLLM())

    r = await svc.create_reminder(session, "起床", "2026-06-13 08:00", "once")
    await svc.fire_reminder(session, r, datetime(2026, 6, 13, 0, 1))

    assert len(emitted) == 1
    assert emitted[0]["type"] == "message"
    assert "起床" in emitted[0]["content"] or "主人" in emitted[0]["content"]
    assert r.is_active is False  # once 触发后失活


@pytest.mark.asyncio
async def test_fire_reminder_llm_failure_uses_fallback(session, monkeypatch):
    from types import SimpleNamespace

    emitted = []

    async def fake_emit(event):
        emitted.append(event)

    async def fake_save(robot_id, robot_name, content):
        pass

    async def fake_pick(s):
        return SimpleNamespace(id="r1", name="小诺", personality=[])

    class BoomLLM:
        async def generate(self, messages, system_prompt="", temperature=0.7):
            raise RuntimeError("llm down")

    monkeypatch.setattr(svc, "_heartbeat_emit", fake_emit)
    monkeypatch.setattr(svc, "_heartbeat_save", fake_save)
    monkeypatch.setattr(svc, "_pick_robot", fake_pick)
    monkeypatch.setattr(svc, "_make_flash_llm", lambda: BoomLLM())

    r = await svc.create_reminder(session, "吃药", "2026-06-13 08:00", "once")
    await svc.fire_reminder(session, r, datetime(2026, 6, 13, 0, 1))
    assert len(emitted) == 1
    assert "吃药" in emitted[0]["content"]  # 兜底文案必含提醒内容
```

- [ ] **Step 2**: 运行确认失败，`app/services/reminders.py` 末尾追加：

```python
# ---------- 触发与循环（由 FastAPI lifespan 启动，独立于 heartbeat 睡眠状态） ----------

import asyncio
import random

REMINDER_CHECK_INTERVAL = 30  # 秒


def _make_flash_llm():
    from app.services.llm.deepseek import DeepSeekLLM
    return DeepSeekLLM(model="deepseek-v4-flash")


async def _heartbeat_emit(event: dict) -> None:
    from app.services.heartbeat import _emit
    await _emit(event)


async def _heartbeat_save(robot_id, robot_name: str, content: str) -> None:
    from app.services.heartbeat import _save_heartbeat_message
    await _save_heartbeat_message(robot_id, robot_name, content)


async def _pick_robot(session: AsyncSession):
    """提醒绑定的角色；未绑定则随机选一个。"""
    from app.db.models import Robot
    robots = list((await session.execute(select(Robot))).scalars().all())
    return random.choice(robots) if robots else None


async def fire_reminder(session: AsyncSession, reminder: Reminder, now_utc: datetime) -> None:
    """到点触发：角色人设化提醒语 → message 事件 + 落库 → 推进/失活。失败也要推进，避免风暴。"""
    robot = None
    if reminder.robot_id:
        from app.db.models import Robot
        robot = (await session.execute(
            select(Robot).where(Robot.id == reminder.robot_id))).scalar_one_or_none()
    if not robot:
        robot = await _pick_robot(session)

    content = f"叮——提醒时间到：{reminder.title}！"  # 兜底文案
    robot_name = robot.name if robot else "系统"
    if robot:
        try:
            personality = robot.personality or []
            if isinstance(personality, dict):
                personality = list(personality.values())
            llm = _make_flash_llm()
            text = await asyncio.wait_for(llm.generate(
                messages=[{"role": "user", "content":
                    f"你是 {robot.name}，性格：{', '.join(str(p) for p in personality[:3])}。"
                    f"主人之前让你到点提醒：「{reminder.title}」。现在到点了，"
                    f"用你的语气喊主人（1-2句话，必须包含提醒的事情本身）。"}],
                system_prompt=f"你是 {robot.name}，正在提醒主人一件事。",
            ), timeout=20)
            if text and reminder.title.strip() and text.strip():
                content = text.strip()
                if reminder.title not in content:
                    content = f"{content}（提醒：{reminder.title}）"
        except Exception as e:
            print(f"[reminders] Persona wrap failed, using fallback: {e}")

    await _heartbeat_emit({
        "type": "message",
        "robot_id": str(robot.id) if robot else "",
        "robot_name": robot_name,
        "content": content,
        "target": None,
    })
    try:
        if robot:
            await _heartbeat_save(robot.id, robot_name, content)
    except Exception as e:
        print(f"[reminders] Save message failed: {e}")
    await advance_after_trigger(session, reminder, now_utc)


async def reminders_loop() -> None:
    """每 REMINDER_CHECK_INTERVAL 秒扫描一次到期提醒。永不退出（除非 cancel）。"""
    from app.db.engine import async_session
    print("[reminders] Check loop started.")
    while True:
        try:
            await asyncio.sleep(REMINDER_CHECK_INTERVAL)
            now = datetime.utcnow()
            async with async_session() as session:
                for reminder in await find_due(session, now):
                    try:
                        await fire_reminder(session, reminder, now)
                    except Exception as e:
                        print(f"[reminders] Fire failed for {reminder.title}: {e}")
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[reminders] Loop error: {e}")
```

- [ ] **Step 3**: `app/main.py` lifespan 改为：

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.is_sqlite:
        from app.db.engine import init_db
        await init_db()
        print("[startup] SQLite database initialized.")
    from app.services.tools.toggles import hydrate_tool_settings
    await hydrate_tool_settings()
    import asyncio
    from app.services.reminders import reminders_loop
    reminder_task = asyncio.create_task(reminders_loop())
    yield
    reminder_task.cancel()
```

（Task 2 已加 hydrate 的话保持一处即可，不要重复。）

- [ ] **Step 4**: `python -m pytest tests/test_reminders_service.py -v` 10 个全过；`python -c "import app.main"` 无错；全量 `python -m pytest tests/ -q` 无新失败
- [ ] **Step 5**: Commit `feat(reminders): persona-voiced trigger via message channel + lifespan check loop`

---

### Task 6: admin 面板工具开关 UI

**Files:** Modify `backend/app/admin_panel.html`

无单测（vanilla JS），靠 Task 7 实测。先读文件头部（标题栏/按钮区，约 190-230 行）和现有 modal 的写法，跟随同样式。

- [ ] **Step 1**: 在页面头部按钮区加一个按钮：`<button class="..." onclick="openToolsModal()">🔧 工具开关</button>`（class 跟随旁边现有按钮）
- [ ] **Step 2**: 在 body 末尾已有 modal 的旁边加：

```html
<div id="tools-modal" class="modal" style="display:none">
  <div class="modal-content" style="max-width:520px">
    <h3 style="margin-bottom:16px">🔧 工具技能开关</h3>
    <div id="tools-list" style="display:flex;flex-direction:column;gap:10px"></div>
    <div style="margin-top:20px;text-align:right">
      <button onclick="document.getElementById('tools-modal').style.display='none'">关闭</button>
    </div>
  </div>
</div>
```

（若现有 modal 用别的 class/结构，跟随现有写法。）

- [ ] **Step 3**: script 区加：

```javascript
async function openToolsModal() {
  const modal = document.getElementById('tools-modal');
  modal.style.display = 'flex';
  const list = document.getElementById('tools-list');
  list.innerHTML = '加载中…';
  const tools = await (await fetch('/api/admin/tools')).json();
  list.innerHTML = '';
  for (const t of tools) {
    const row = document.createElement('div');
    row.style.cssText = 'display:flex;align-items:center;justify-content:space-between;padding:10px 12px;background:#0f0f1a;border:1px solid #2a2a4a;border-radius:8px';
    row.innerHTML = `<div><div style="font-size:14px">${t.display_name} <span style="color:#666;font-size:12px">${t.name}</span></div>
      <div style="color:#888;font-size:12px;margin-top:2px">${t.description}</div></div>
      <label style="cursor:pointer;flex-shrink:0;margin-left:12px">
        <input type="checkbox" ${t.enabled ? 'checked' : ''} onchange="toggleTool('${t.name}', this.checked)"> 启用
      </label>`;
    list.appendChild(row);
  }
}

async function toggleTool(name, enabled) {
  await fetch(`/api/admin/tools/${name}`, {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({enabled}),
  });
}
```

- [ ] **Step 4**: 手动检查：HTML 语法完整（标签闭合）；Commit `feat(admin): tool toggle UI in admin panel`

---

### Task 7: E2E 实测（控制端执行）

- [ ] 重启后端 `pm2 restart nomi-backend`，`/api/health` ok
- [ ] `GET /api/admin/tools` 返回 10 个工具（7 旧 + 3 提醒）全 enabled
- [ ] `PUT /api/admin/tools/weather {"enabled": false}` → 聊天问天气 → 角色不报真实数据；恢复 enabled → 报真实数据
- [ ] 聊天说"X分钟后提醒我喝水"（设 2 分钟后）→ 角色确认 → 等待 → `/api/heartbeat/events` 出现角色提醒消息，Message 表落库
- [ ] 浏览器开 `/admin` 确认开关 UI 正常
- [ ] 全量回归 `python -m pytest tests/ -q` 全绿

---

## 自检（spec 覆盖）

工具开关存储/缓存/生效面/UI（T2/T6）；提醒表（T1）；三工具+时间注入+autonomous（T4）；触发循环+人设化+message 通道（T5）；once/daily+补触发+歧义取消（T3）；E2E（T7）。
