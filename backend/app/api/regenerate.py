"""Regenerate individual modules of a robot's profile."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.engine import get_session
from app.db.models import Robot, YearlyMemory
from app.prompts.creation import (
    build_batch_memories_prompt,
    build_portrait_prompt,
    build_robot_creation_from_image_prompt,
    _compute_batches,
    _compute_target_count,
)
from app.services.llm.factory import create_llm

router = APIRouter(prefix="/api/robots/{robot_id}/regenerate", tags=["regenerate"])

MODELS = {
    "claude": ("claude-cli", {}),
    "deepseek-v4-flash": ("deepseek", {"model": "deepseek-v4-flash"}),
    "deepseek-v4-pro": ("deepseek", {"model": "deepseek-v4-pro"}),
}


def _get_llm(model_key: str):
    if model_key.startswith("deepseek"):
        from app.services.llm.deepseek import DeepSeekLLM
        return DeepSeekLLM(model=model_key)
    else:
        return create_llm(
            settings.llm_provider,
            anthropic_api_key=settings.anthropic_api_key,
            openai_api_key=settings.openai_api_key,
        )


@router.post("/personality")
async def regenerate_personality(
    robot_id: uuid.UUID,
    model: str = Query(default="deepseek-v4-flash"),
    session: AsyncSession = Depends(get_session),
):
    """Regenerate personality traits, desire, fear."""
    result = await session.execute(select(Robot).where(Robot.id == robot_id))
    robot = result.scalar_one_or_none()
    if not robot:
        return {"error": "not found"}

    llm = _get_llm(model)

    # Get existing robots for differentiation
    others = await session.execute(
        select(Robot).where(Robot.user_id == robot.user_id, Robot.id != robot_id)
    )
    existing = [{"name": r.name, "personality": r.personality} for r in others.scalars().all()]

    # Use origin_story as object description
    desc = robot.origin_story or robot.name
    sys_p, usr_p = build_robot_creation_from_image_prompt(desc, existing)
    profile = await llm.generate_structured(
        messages=[{"role": "user", "content": usr_p}], system_prompt=sys_p,
    )

    robot.personality = profile.get("core_personality", robot.personality)
    robot.core_desire = profile.get("core_desire", robot.core_desire)
    robot.core_fear = profile.get("core_fear", robot.core_fear)
    robot.speaking_style = profile.get("speaking_style", robot.speaking_style)

    # Update inner_drives if present
    import json
    inner_drives = profile.get("inner_drives", {})
    if inner_drives:
        robot.current_status = json.dumps({"inner_drives": inner_drives}, ensure_ascii=False)

    await session.commit()

    return {
        "personality": robot.personality,
        "core_desire": robot.core_desire,
        "core_fear": robot.core_fear,
        "speaking_style": robot.speaking_style,
        "model": model,
    }


@router.post("/origin-story")
async def regenerate_origin_story(
    robot_id: uuid.UUID,
    model: str = Query(default="claude"),
    session: AsyncSession = Depends(get_session),
):
    """Regenerate origin story."""
    result = await session.execute(select(Robot).where(Robot.id == robot_id))
    robot = result.scalar_one_or_none()
    if not robot:
        return {"error": "not found"}

    llm = _get_llm(model)

    prompt = f"""你是 {robot.name}，一个有生命的物品。
性格：{robot.personality}
愿望：{robot.core_desire}
恐惧：{robot.core_fear}
出生地：{robot.birth_place}
年龄：{robot.age}岁

请用第一人称重新写你的出生故事（200-400字）。
要有具体的场景、感官细节、情感。
直接写故事，不要加标题。"""

    origin = await llm.generate(
        messages=[{"role": "user", "content": prompt}],
    )

    robot.origin_story = origin
    await session.commit()

    return {"origin_story": origin, "model": model}


@router.post("/portrait")
async def regenerate_portrait(
    robot_id: uuid.UUID,
    model: str = Query(default="deepseek-v4-flash"),
    session: AsyncSession = Depends(get_session),
):
    """Regenerate the complete portrait/soul."""
    from app.prompts.creation import build_portrait_prompt

    result = await session.execute(select(Robot).where(Robot.id == robot_id))
    robot = result.scalar_one_or_none()
    if not robot:
        return {"error": "not found"}

    llm = _get_llm(model)

    # Gather all memories
    from app.db.models import Memory
    mem_result = await session.execute(
        select(Memory).where(Memory.owner_id == robot_id).where(Memory.importance_score > 0.2)
    )
    memories = list(mem_result.scalars().all())

    mem_data = [
        {"time": f"记忆", "summary": m.summary or (m.content[:100] if m.content else ""), "strength": m.importance_score or 0.5}
        for m in memories
    ]

    sys_p, usr_p = build_portrait_prompt(
        robot_name=robot.name, robot_age=robot.age or 0,
        object_description=robot.origin_story or "",
        personality=robot.personality or [],
        core_desire=robot.core_desire or "",
        core_fear=robot.core_fear or "",
        life_theme="",
        all_memories_with_strength=mem_data,
    )

    portrait = await llm.generate_structured(
        messages=[{"role": "user", "content": usr_p}], system_prompt=sys_p,
    )

    robot.portrait = portrait
    await session.commit()

    return {"portrait": portrait, "model": model}


@router.post("/memories")
async def regenerate_memories(
    robot_id: uuid.UUID,
    model: str = Query(default="claude"),
    session: AsyncSession = Depends(get_session),
):
    """Regenerate all life memories (delete old ones and create new)."""
    import math
    from sqlalchemy import delete

    result = await session.execute(select(Robot).where(Robot.id == robot_id))
    robot = result.scalar_one_or_none()
    if not robot:
        return {"error": "not found"}

    llm = _get_llm(model)

    # Delete old yearly memories
    await session.execute(delete(YearlyMemory).where(YearlyMemory.robot_id == robot_id))
    await session.commit()

    robot_age = robot.age or 5
    description = robot.origin_story or robot.name
    batches = _compute_batches(robot_age)
    total_target = _compute_target_count(robot_age)
    per_batch = max(5, total_target // len(batches))

    ongoing_state = None
    life_theme = ""
    all_memories = []
    total_words = 0
    memory_count = 0

    failed_batches = 0
    for batch_idx, (start_age, end_age) in enumerate(batches):
        prev_tail = all_memories[-3:] if all_memories else None

        sys_msg, usr_msg = build_batch_memories_prompt(
            robot_name=robot.name, robot_age=robot_age,
            object_description=description,
            personality=robot.personality or [],
            core_desire=robot.core_desire or "",
            core_fear=robot.core_fear or "",
            birth_place=robot.birth_place or "",
            batch_start_age=start_age, batch_end_age=end_age,
            target_count=per_batch, batch_index=batch_idx,
            total_batches=len(batches),
            ongoing_state=ongoing_state,
            previous_memories_tail=prev_tail,
            life_theme=life_theme,
        )

        # Per-batch fault isolation: one bad LLM response (non-JSON, etc.) must
        # not abort the whole regeneration — skip it and keep the rest.
        try:
            batch_result = await llm.generate_structured(
                messages=[{"role": "user", "content": usr_msg}],
                system_prompt=sys_msg,
            )
            if not isinstance(batch_result, dict):
                raise ValueError(f"non-dict batch result: {type(batch_result).__name__}")
        except Exception as e:
            failed_batches += 1
            print(f"[regenerate_memories] batch {batch_idx} (age {start_age}-{end_age}) failed: {e}")
            continue

        if batch_idx == 0:
            life_theme = batch_result.get("life_theme", "")

        ongoing_state = batch_result.get("ongoing_state")
        batch_memories = batch_result.get("memories", []) or []

        for mem_data in batch_memories:
            if not isinstance(mem_data, dict):
                continue
            content = mem_data.get("content", "") or ""
            importance = mem_data.get("importance", 0.5)
            approx_age = mem_data.get("approximate_age", start_age)
            years_ago = max(0, robot_age - approx_age)
            decay = math.exp(-0.08 * years_ago)
            strength = round(max(decay, importance * 0.7), 2)
            word_count = len(content)
            total_words += word_count

            # Always populate memory_summary (some models fill content but no
            # explicit summary field) so downstream display/prompts are not empty.
            summary = (mem_data.get("summary") or "").strip()
            if not summary and content:
                summary = (content[:55] + "…") if len(content) > 55 else content

            mem = YearlyMemory(
                robot_id=robot.id, age=approx_age,
                memory_title=mem_data.get("title", ""),
                memory_content=content,
                memory_summary=summary,
                emotional_impact={"core": mem_data.get("emotional_core", "")},
                memory_type=mem_data.get("memory_type", "fragment"),
                importance=importance, memory_strength=strength,
                word_count=word_count, batch_index=batch_idx,
                symbolic_tags=[],
            )
            session.add(mem)

            all_memories.append({
                "time": mem_data.get("time", ""),
                "content": content,
                "strength": strength,
            })
            memory_count += 1

        # Commit per batch so a later failure never loses earlier batches.
        try:
            if ongoing_state and ongoing_state.get("relationships"):
                robot.relationships_snapshot = ongoing_state["relationships"]
            await session.commit()
        except Exception as e:
            await session.rollback()
            print(f"[regenerate_memories] batch {batch_idx} commit failed: {e}")

    return {
        "moment_count": memory_count,
        "total_words": total_words,
        "model": model,
        "failed_batches": failed_batches,
    }
