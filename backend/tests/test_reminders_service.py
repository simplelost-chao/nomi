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
        # Only create the tables this service needs (avoids PG-only types in robots table)
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[Reminder.__table__],
        )
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


@pytest.mark.asyncio
async def test_refire_guard_blocks_within_window(session, monkeypatch):
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
            return "提醒啦"

    monkeypatch.setattr(svc, "_heartbeat_emit", fake_emit)
    monkeypatch.setattr(svc, "_heartbeat_save", fake_save)
    monkeypatch.setattr(svc, "_pick_robot", fake_pick)
    monkeypatch.setattr(svc, "_make_flash_llm", lambda: FakeLLM())
    svc._recently_fired.clear()

    now = datetime(2026, 6, 13, 0, 1)
    r = await svc.create_reminder(session, "起床", "2026-06-13 08:00", "once")
    await svc.fire_reminder(session, r, now)
    assert str(r.id) in svc._recently_fired  # emit 后立即登记，advance 失败也有记录
