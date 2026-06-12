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
