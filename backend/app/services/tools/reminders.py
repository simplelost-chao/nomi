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
