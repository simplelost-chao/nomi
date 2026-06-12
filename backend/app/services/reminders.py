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


# ---------- 触发与循环（由 FastAPI lifespan 启动，独立于 heartbeat 睡眠状态） ----------

import asyncio
import random

REMINDER_CHECK_INTERVAL = 30  # 秒
_REFIRE_GUARD_SECONDS = 600  # advance 落库失败时的内存防重发窗口
_recently_fired: dict[str, datetime] = {}  # reminder_id -> fired_at (utc)


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
    _recently_fired[str(reminder.id)] = now_utc
    if len(_recently_fired) > 200:
        cutoff = now_utc - timedelta(seconds=_REFIRE_GUARD_SECONDS)
        for k in [k for k, v in _recently_fired.items() if v < cutoff]:
            _recently_fired.pop(k, None)
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
                    fired_at = _recently_fired.get(str(reminder.id))
                    if fired_at and (now - fired_at).total_seconds() < _REFIRE_GUARD_SECONDS:
                        continue  # 已触发但 advance 落库失败过：窗口内不重发
                    try:
                        await fire_reminder(session, reminder, now)
                    except Exception as e:
                        print(f"[reminders] Fire failed for {reminder.title}: {e}")
                        try:
                            await session.rollback()
                        except Exception:
                            pass
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[reminders] Loop error: {e}")
