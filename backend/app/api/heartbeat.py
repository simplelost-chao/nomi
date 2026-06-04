"""Heartbeat API — wake/sleep toggle + event polling + manual triggers."""

import asyncio
import json
import uuid
from collections import deque

from fastapi import APIRouter

from app.services.heartbeat import (
    wake_up, fall_asleep, is_alive, is_busy, set_busy,
    set_heartbeat_interval, get_heartbeat_interval,
    add_listener, remove_listener,
)

router = APIRouter(prefix="/api/heartbeat", tags=["heartbeat"])

# Event buffer for polling (last 100 events)
_events: deque[dict] = deque(maxlen=100)
_event_counter = 0


async def _on_event(event: dict):
    global _event_counter
    _event_counter += 1
    event["seq"] = _event_counter
    import time
    event["timestamp"] = time.time()
    _events.append(event)


# Register listener on startup
add_listener(_on_event)


@router.post("/wake")
async def wake():
    global _event_counter
    _events.clear()
    _event_counter = 0
    await wake_up()
    return {"status": "awake"}


@router.post("/sleep")
async def sleep():
    await fall_asleep()
    return {"status": "sleeping"}


@router.post("/busy")
async def busy(busy: bool = True):
    """Signal that frontend is playing TTS — heartbeat pauses."""
    set_busy(busy)
    return {"busy": is_busy()}


@router.post("/interval")
async def set_interval(seconds: int = 5):
    """Set heartbeat interval in seconds (1-60)."""
    set_heartbeat_interval(seconds)
    return {"interval": get_heartbeat_interval()}


@router.get("/status")
async def status():
    return {"alive": is_alive(), "interval": get_heartbeat_interval()}


@router.get("/events")
async def get_events(after: int = 0):
    """Poll for new events. Pass `after` as the last seen seq number."""
    new_events = [e for e in _events if e.get("seq", 0) > after]
    return {"events": new_events, "alive": is_alive()}


async def _generate_thought(robot, llm) -> str | None:
    """Generate a single thought for the robot using the real heartbeat prompt."""
    from app.services.heartbeat import _build_trigger, _get_inner_drives, THOUGHT_PROMPT

    trigger = await _build_trigger(robot, [], beat_count=0, recent_thoughts=[], llm=llm)

    drives = _get_inner_drives(robot)
    drives_parts = []
    if drives.get("curiosity", 0) > 0.5:
        topics = drives.get("curiosity_about", [])
        drives_parts.append(f"你很好奇，尤其对{'、'.join(topics[:3]) if topics else '很多事情'}感兴趣")
    if drives.get("introspection", 0) > 0.5:
        drives_parts.append("你经常思考自我和存在的意义")
    if drives.get("playfulness", 0) > 0.7:
        drives_parts.append("你喜欢玩闹和开玩笑")
    drives_desc = "你的内在特质：" + "；".join(drives_parts) if drives_parts else ""

    prompt = THOUGHT_PROMPT.format(
        name=robot.name,
        personality=json.dumps(robot.personality or [], ensure_ascii=False),
        desire=robot.core_desire or "",
        fear=robot.core_fear or "",
        drives_desc=drives_desc,
        context="",
        current_conversation="",
        trigger=trigger,
        recent_thoughts="（手动触发）",
        awake_minutes=0,
    )

    try:
        data = await llm.generate_structured(messages=[{"role": "user", "content": prompt}])
        return data.get("thought") or data.get("say") or None
    except Exception:
        return None


@router.post("/trigger/{robot_id}/{action}")
async def trigger_action(robot_id: str, action: str):
    """Manually trigger a single heartbeat action for a specific robot.
    action: thought | search | skill | reflect
    """
    from sqlalchemy import select
    from app.db.engine import async_session
    from app.db.models import Robot
    from app.services.llm.deepseek import DeepSeekLLM

    async with async_session() as session:
        robot = (await session.execute(
            select(Robot).where(Robot.id == uuid.UUID(robot_id))
        )).scalar_one_or_none()
        if not robot:
            return {"error": "robot not found"}

        llm = DeepSeekLLM(model="deepseek-v4-flash")

        if action == "thought":
            from app.services.memory_evolution import save_thought_memory
            from app.services.activity import log_activity

            thought = await _generate_thought(robot, llm)
            if thought:
                await save_thought_memory(session, robot, thought, base_importance=0.2, llm=llm)
                await session.commit()
                async with async_session() as log_s:
                    await log_activity(log_s, robot.id, "thought", thought)
                await _on_event({"type": "thought", "robot": robot.name, "message": thought})
                return {"action": "thought", "result": thought}
            return {"action": "thought", "result": None}

        elif action == "search":
            from app.services.web_search import search_topic
            from app.services.memory_evolution import save_thought_memory
            from app.services.activity import log_activity
            from app.services.heartbeat import _get_inner_drives

            # Extract a real-world Wikipedia topic inspired by the robot's interests
            drives = _get_inner_drives(robot)
            curiosity_topics = drives.get("curiosity_about", [])
            curiosity_str = "、".join(curiosity_topics[:3]) if curiosity_topics else ""

            personality = robot.personality or []
            if isinstance(personality, dict):
                personality = list(personality.values())

            extract_prompt = f"""你是 {robot.name}，{robot.age or 0}岁，性格：{', '.join(str(p) for p in personality[:3])}
愿望：{robot.core_desire or ''}
好奇的方向：{curiosity_str or '（无）'}

请基于你的性格和好奇心，联想一个你想去百科全书查阅的【真实世界的话题】。
要求：
- 必须是现实中存在的具体事物、概念、现象（如"极光"、"章鱼的智商"、"日本金缮修复"）
- 不能搜你自己的名字或虚构内容
- 2-8个汉字

只输出话题词，不要其他内容："""
            query = await llm.generate(messages=[{"role": "user", "content": extract_prompt}])
            query = (query or "星星").strip().strip('"').strip("'").replace("?", "").replace("？", "")[:20]

            await _on_event({"type": "system", "robot": robot.name, "message": f"🔍 正在搜索「{query}」..."})
            result = await search_topic(robot, query)
            if result:
                knowledge = f"[学到的知识] {result.get('summary', '')}"
                await save_thought_memory(session, robot, knowledge, base_importance=0.6, llm=llm)
                for fact in (result.get("key_facts") or [])[:3]:
                    if fact:
                        await save_thought_memory(session, robot, f"[知识碎片] {fact}", base_importance=0.45, llm=llm)
                await session.commit()
                async with async_session() as log_s:
                    await log_activity(log_s, robot.id, "learn", result.get("summary", ""), detail=result)
                await _on_event({"type": "thought", "robot": robot.name, "message": f"📚 学到了：{result.get('summary', '')[:80]}"})
                return {"action": "search", "query": query, "result": result}
            return {"action": "search", "query": query, "result": None}

        elif action == "skill":
            from app.services.skills import discover_skill
            from app.services.activity import log_activity

            skill = await discover_skill(robot, session, llm, beat_count=9999)
            if skill:
                async with async_session() as log_s:
                    await log_activity(log_s, robot.id, "skill_acquired", f"习得技能：{skill.name}",
                                       detail={"name": skill.name, "description": skill.description, "type": skill.skill_type})
                await _on_event({"type": "skill_acquired", "robot": robot.name,
                                 "message": f"🌱 {robot.name} 习得了新技能：{skill.name}"})
                return {"action": "skill", "skill": {"name": skill.name, "description": skill.description}}
            return {"action": "skill", "result": "no new skill generated (may have hit cap or cooldown)"}

        elif action == "reflect":
            from app.services.memory_evolution import save_thought_memory
            from app.services.activity import log_activity
            from sqlalchemy import select as sa_select
            from app.db.models import YearlyMemory

            memories = (await session.execute(
                sa_select(YearlyMemory)
                .where(YearlyMemory.robot_id == robot.id)
                .order_by(YearlyMemory.importance.desc().nullslast())
                .limit(5)
            )).scalars().all()
            mem_texts = "\n".join(f"- {m.memory_content[:100]}" for m in memories if m.memory_content)

            personality = robot.personality or []
            if isinstance(personality, dict):
                personality = list(personality.values())

            prompt = f"""你就是 {robot.name}，{robot.age or 0}岁，要用你自己的口吻和性格说话。
你的性格：{', '.join(str(p) for p in personality[:4])}
你现在的心愿/处境：{robot.core_desire or ''}

你脑海里浮现的一些过往片段：
{mem_texts or '（暂无）'}

请用【你自己的声音、你这个年龄该有的样子】，写一小段此刻的内心想法（40-70字，第一人称）。
要求：
- 完全保持角色的语气和性格，绝不要写成大人式的、忧郁的、说教的反思
- 就算想起以前难过的事，也要从你"现在"的视角看（你现在是被爱着的、安全的、有家的）
- 真实、具体、有这个角色独有的味道，不要空泛感慨"""

            reflection = await llm.generate(messages=[{"role": "user", "content": prompt}])
            if reflection:
                reflection = reflection.strip()
                await save_thought_memory(session, robot, f"[反思] {reflection}", base_importance=0.7, llm=llm)
                await session.commit()
                async with async_session() as log_s:
                    await log_activity(log_s, robot.id, "reflect", reflection)
                await _on_event({"type": "thought", "robot": robot.name, "message": f"🪞 {reflection}"})
                return {"action": "reflect", "result": reflection}
            return {"action": "reflect", "result": None}

        return {"error": f"unknown action: {action}"}
