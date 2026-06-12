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
