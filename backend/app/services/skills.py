"""Skill evolution — robots autonomously discover and execute self-defined skills."""

import asyncio
import json
import random
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Robot, RobotSkill, YearlyMemory
from app.services.llm.base import BaseLLM


# How many heartbeat cycles to wait between skill discovery attempts
_DISCOVERY_COOLDOWN_BEATS = 200   # ~1000s ≈ 17 min between attempts
_last_discovery: dict[str, int] = {}  # robot_id -> beat_count


def should_attempt_discovery(robot: Robot, beat_count: int, skill_count: int) -> bool:
    """Check if conditions are right to attempt skill discovery."""
    # Need some age and energy
    if (robot.energy or 0) < 30:
        return False

    # Cooldown between attempts
    last = _last_discovery.get(str(robot.id), -_DISCOVERY_COOLDOWN_BEATS)
    if beat_count - last < _DISCOVERY_COOLDOWN_BEATS:
        return False

    # Introspection drive gates probability
    from app.services.heartbeat import _get_inner_drives
    drives = _get_inner_drives(robot)
    introspection = drives.get("introspection", 0.5)

    # Base 1% per eligible heartbeat, boosted by introspection
    # More skills = harder to learn new ones (diminishing returns)
    prob = 0.01 + introspection * 0.03
    prob *= max(0.2, 1.0 - skill_count * 0.1)

    return random.random() < prob


async def discover_skill(
    robot: Robot,
    session: AsyncSession,
    llm: BaseLLM,
    beat_count: int,
) -> RobotSkill | None:
    """Ask the robot to define a new skill it wants to learn. Returns saved skill or None."""
    _last_discovery[str(robot.id)] = beat_count

    # Load existing skills (to avoid duplicates)
    existing = (await session.execute(
        select(RobotSkill).where(RobotSkill.robot_id == robot.id)
    )).scalars().all()

    if len(existing) >= 12:  # Cap at 12 skills per robot
        return None

    existing_names = [s.name for s in existing]

    # Get a few recent memories for context
    memories = (await session.execute(
        select(YearlyMemory)
        .where(YearlyMemory.robot_id == robot.id)
        .order_by(YearlyMemory.importance.desc().nullslast())
        .limit(5)
    )).scalars().all()
    memory_texts = [m.memory_content[:100] for m in memories if m.memory_content]

    personality = robot.personality or []
    if isinstance(personality, dict):
        personality = list(personality.values())

    existing_str = "、".join(existing_names) if existing_names else "（还没有技能）"
    memory_str = "\n".join(f"- {m}" for m in memory_texts[:3]) if memory_texts else "（暂无记忆）"

    prompt = f"""你是 {robot.name}，{robot.age or 0}岁，来自{robot.birth_place or '未知地方'}。
性格：{', '.join(str(p) for p in personality[:4])}
核心愿望：{robot.core_desire or '未知'}
核心恐惧：{robot.core_fear or '未知'}

你最重要的一些记忆：
{memory_str}

你已掌握的技能：{existing_str}

你在反思中领悟到一种新的表达或交流能力。这个技能是你在【对话中能实际做到的事情】。

注意：技能必须是对话中可以展现的行为，不是魔法或超能力。
好的例子：讲冷笑话、编睡前故事、用比喻解释复杂的事、安慰伤心的人、模仿别人说话、分享冷知识、起外号、用反问引导思考
坏的例子：让眼睛发光、操控天气、飞行、变身（这些是幻想，不是技能）

请定义这项技能，只输出合法 JSON：
{{
  "name": "技能名称（2-6字，不要重复已有技能）",
  "description": "这个技能是什么，你为什么擅长它（50字内，第一人称）",
  "trigger_keywords": ["触发词1", "触发词2", "触发词3", "触发词4"],
  "execution_prompt": "你在对话中用这个技能时具体怎么说话或表现（80字内，第一人称，要具体可执行）",
  "skill_type": "creative或knowledge或social中选一个"
}}"""

    try:
        result = await llm.generate_structured(
            messages=[{"role": "user", "content": prompt}],
            system_prompt="定义一个对话中能实际表现的技能，不要幻想或超能力。只输出 JSON。",
        )
    except Exception as e:
        print(f"[skills] Discovery LLM failed: {e}")
        return None

    name = result.get("name", "").strip()
    if not name or name in existing_names:
        return None

    skill = RobotSkill(
        robot_id=robot.id,
        name=name,
        description=result.get("description"),
        trigger_keywords=result.get("trigger_keywords", []),
        execution_prompt=result.get("execution_prompt"),
        skill_type=result.get("skill_type", "creative"),
        usage_count=0,
        acquired_at=datetime.utcnow(),
    )
    session.add(skill)
    await session.commit()
    await session.refresh(skill)
    return skill


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
        result = await asyncio.wait_for(tool.execute(params or {}), timeout=tool.timeout)
    except Exception as e:
        result = ToolResult(ok=False, error=str(e))
    if not result.ok:
        print(f"[skills] Tool {skill.tool_name} failed: {result.error}")
        return None

    prompt = f"""你是 {robot.name}。你刚用「{skill.name}」查到了真实信息：
{result.summary[:1000]}

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


def find_triggered_skill(skills: list[RobotSkill], thought: str) -> RobotSkill | None:
    """Return the first skill whose trigger_keywords appear in the thought, or None."""
    if not thought:
        return None
    for skill in skills:
        keywords = skill.trigger_keywords or []
        if any(kw and kw in thought for kw in keywords):
            return skill
    return None


async def get_robot_skills(session: AsyncSession, robot_id) -> list[RobotSkill]:
    result = await session.execute(
        select(RobotSkill).where(RobotSkill.robot_id == robot_id)
        .order_by(RobotSkill.acquired_at)
    )
    return list(result.scalars().all())
