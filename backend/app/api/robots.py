import asyncio
import json
import math
import time
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.engine import get_session, async_session
from app.db.models import Robot, User, YearlyMemory
from app.prompts.creation import (
    build_batch_memories_prompt,
    build_portrait_prompt,
    build_robot_creation_from_image_prompt,
    _compute_batches,
    _compute_target_count,
)
from app.schemas import RobotCreate, RobotDetail, RobotOut
from app.services.llm.factory import create_llm
from app.services.robot import RobotService
from app.services.vision import VisionService

router = APIRouter(prefix="/api/robots", tags=["robots"])
DEFAULT_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

_creation_jobs: dict[str, dict] = {}


def get_llm():
    return create_llm(
        settings.llm_provider,
        anthropic_api_key=settings.anthropic_api_key,
        openai_api_key=settings.openai_api_key,
    )


@router.post("/from-image")
async def create_robot_from_image(
    image: UploadFile | None = File(None),
    text_hint: str = Form(""),
):
    if not image and not text_hint.strip():
        raise HTTPException(status_code=400, detail="请上传图片或描述物品")

    image_bytes = await image.read() if image else None
    job_id = str(uuid.uuid4())

    # Save uploaded image as avatar
    avatar_path = None
    if image_bytes:
        import os
        avatar_dir = "/Users/chao/projects/nomi/frontend/public/avatars"
        os.makedirs(avatar_dir, exist_ok=True)
        avatar_filename = f"{job_id}.jpg"
        with open(os.path.join(avatar_dir, avatar_filename), "wb") as f:
            f.write(image_bytes)
        avatar_path = f"/avatars/{avatar_filename}"

    _creation_jobs[job_id] = {
        "status": "started",
        "steps": [
            {"id": "identify", "label": "识别物品", "status": "pending"},
            {"id": "personality", "label": "想象性格", "status": "pending"},
            {"id": "memories", "label": "生成记忆碎片", "status": "pending"},
            {"id": "portrait", "label": "生成完整画像", "status": "pending"},
            {"id": "voice", "label": "生成专属声音", "status": "pending"},
        ],
        "robot": None,
        "portrait": None,
        "stats": None,
        "error": None,
        "memories_done": 0,
        "memories_total": 0,
        "current_memory": None,
        "total_words": 0,
    }

    asyncio.create_task(_run_creation(job_id, image_bytes, text_hint.strip(), avatar_path))
    return {"job_id": job_id}


@router.get("/creation-status/{job_id}")
async def get_creation_status(job_id: str):
    job = _creation_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


async def _run_creation(job_id: str, image_bytes: bytes | None, text_hint: str, avatar_path: str | None = None):
    job = _creation_jobs[job_id]

    try:
        async with async_session() as session:
            llm = get_llm()  # Claude CLI — quality first
            total_cost = 0.0
            gen_start = time.time()

            def _get_llm_stats():
                return {
                    "cost_usd": round(getattr(llm, "last_cost_usd", 0.0), 4),
                    "duration_ms": getattr(llm, "last_duration_ms", 0),
                }

            def _track():
                nonlocal total_cost
                total_cost += getattr(llm, "last_cost_usd", 0.0)

            # === 1. Identify ===
            t0 = time.time()
            _set_step(job, "identify", "running")

            if image_bytes:
                vision = VisionService()
                obj_info = await vision.identify_object(
                    image_bytes=image_bytes, text_hint=text_hint or None,
                )
                object_name = obj_info.get("object_name", "")

                # Build rich description from all identified features
                parts = [f"物品：{object_name}"]
                if obj_info.get("category"):
                    parts.append(f"类型：{obj_info['category']}")
                if obj_info.get("description"):
                    parts.append(obj_info["description"])
                if obj_info.get("material"):
                    parts.append(f"材质：{obj_info['material']}")
                if obj_info.get("color_palette"):
                    parts.append(f"色彩：{obj_info['color_palette']}")
                if obj_info.get("texture"):
                    parts.append(f"触感：{obj_info['texture']}")
                if obj_info.get("size_feeling"):
                    parts.append(f"大小：{obj_info['size_feeling']}")
                if obj_info.get("wear_signs"):
                    parts.append(f"使用痕迹：{obj_info['wear_signs']}")
                if obj_info.get("distinctive_features"):
                    parts.append(f"特征：{'、'.join(obj_info['distinctive_features'])}")
                if obj_info.get("story_hints"):
                    parts.append(f"推测经历：{obj_info['story_hints']}")
                if obj_info.get("emotional_impression"):
                    parts.append(f"第一印象：{obj_info['emotional_impression']}")

                description = "。".join(parts)

                elapsed = int((time.time() - t0) * 1000)
                detail_text = f"{object_name}"
                if obj_info.get("material"):
                    detail_text += f" · {obj_info['material']}"
                if obj_info.get("emotional_impression"):
                    detail_text += f" · {obj_info['emotional_impression']}"
                _set_step(job, "identify", "done",
                          detail=detail_text,
                          time_ms=elapsed, provider="Gemini")
            else:
                description = text_hint
                _set_step(job, "identify", "done", detail="了解了这个物品", time_ms=0)

            # Ensure user
            result = await session.execute(select(User).where(User.id == DEFAULT_USER_ID))
            if not result.scalar_one_or_none():
                session.add(User(id=DEFAULT_USER_ID))
                await session.commit()

            # === 2. Personality ===
            t0 = time.time()
            _set_step(job, "personality", "running")

            existing = await RobotService(session=session, llm=llm).get_robots(DEFAULT_USER_ID)
            existing_summaries = [{"name": r.name, "personality": r.personality} for r in existing]
            sys_p, usr_p = build_robot_creation_from_image_prompt(description, existing_summaries)
            profile = await llm.generate_structured(
                messages=[{"role": "user", "content": usr_p}], system_prompt=sys_p,
            )
            stats = _get_llm_stats()
            _track()

            robot_name = profile.get("name", "小生命")
            robot_age = profile.get("age", 5)
            personality = profile.get("core_personality", [])
            core_desire = profile.get("core_desire", "")
            core_fear = profile.get("core_fear", "")
            birth_place = profile.get("birth_place", "")

            elapsed = int((time.time() - t0) * 1000)
            _set_step(job, "personality", "done",
                      detail=f"它叫 {robot_name}，{'/'.join(personality)}",
                      time_ms=elapsed, cost_usd=stats["cost_usd"])

            inner_drives = profile.get("inner_drives", {})

            robot = Robot(
                user_id=DEFAULT_USER_ID, name=robot_name, age=robot_age,
                birth_place=birth_place, origin_story="",
                core_desire=core_desire, core_fear=core_fear, personality=personality,
                speaking_style=profile.get("speaking_style"),
                voice_profile={**(profile.get("voice_profile") or {}), **({"avatar": avatar_path} if avatar_path else {})},
                current_emotion={"emotion": "calm", "intensity": 0.3},
                current_status=json.dumps({"inner_drives": inner_drives}, ensure_ascii=False),
                energy=100.0,
                generation_stats={"status": "creating", "job_id": job_id, "steps": job["steps"]},
            )
            session.add(robot)
            await session.commit()
            await session.refresh(robot)

            # Link job to robot so detail page can show progress
            job["robot_db_id"] = str(robot.id)

            job["robot"] = {
                "id": str(robot.id), "name": robot.name, "age": robot.age,
                "birth_place": robot.birth_place, "personality": robot.personality,
                "core_desire": robot.core_desire, "core_fear": robot.core_fear,
            }

            # === 3. Generate memory fragments in batches ===
            # Use DeepSeek for memories (fast), Claude for portrait (quality)
            from app.services.llm.deepseek import DeepSeekLLM
            mem_llm = DeepSeekLLM(model="deepseek-v4-flash")

            t0_all = time.time()
            _set_step(job, "memories", "running")

            batches = _compute_batches(robot_age)
            total_target = _compute_target_count(robot_age)
            per_batch = max(5, total_target // len(batches))

            ongoing_state = None
            life_theme = ""
            all_memories = []  # list of {"time": ..., "content": ..., "strength": ...}
            total_words = 0
            memories_cost = 0.0
            memory_count = 0

            job["memories_total"] = total_target

            for batch_idx, (start_age, end_age) in enumerate(batches):
                job["current_memory"] = f"第{batch_idx + 1}批：{start_age}-{end_age}岁"

                # Last 3 memories from previous batch for overlap context
                prev_tail = all_memories[-3:] if all_memories else None

                sys_msg, usr_msg = build_batch_memories_prompt(
                    robot_name=robot_name, robot_age=robot_age,
                    object_description=description,
                    personality=personality, core_desire=core_desire,
                    core_fear=core_fear, birth_place=birth_place,
                    batch_start_age=start_age, batch_end_age=end_age,
                    target_count=per_batch, batch_index=batch_idx,
                    total_batches=len(batches),
                    ongoing_state=ongoing_state,
                    previous_memories_tail=prev_tail,
                    life_theme=life_theme,
                )

                batch_result = await mem_llm.generate_structured(
                    messages=[{"role": "user", "content": usr_msg}],
                    system_prompt=sys_msg,
                )
                mem_cost = getattr(mem_llm, "last_cost_usd", 0.0)
                mem_duration = getattr(mem_llm, "last_duration_ms", 0)
                memories_cost += mem_cost

                # Extract life_theme from first batch
                if batch_idx == 0:
                    life_theme = batch_result.get("life_theme", "")

                ongoing_state = batch_result.get("ongoing_state")
                batch_memories = batch_result.get("memories", [])

                for mem_data in batch_memories:
                    content = mem_data.get("content", "")
                    importance = mem_data.get("importance", 0.5)
                    approx_age = mem_data.get("approximate_age", start_age)
                    years_ago = max(0, robot_age - approx_age)
                    decay = math.exp(-0.08 * years_ago)
                    strength = round(max(decay, importance * 0.7), 2)
                    word_count = len(content)
                    total_words += word_count

                    mem = YearlyMemory(
                        robot_id=robot.id, age=approx_age,
                        memory_title=mem_data.get("title", ""),
                        memory_content=content,
                        emotional_impact={"core": mem_data.get("emotional_core", "")},
                        memory_type=mem_data.get("memory_type", "fragment"),
                        importance=importance, memory_strength=strength,
                        word_count=word_count,
                        generation_time_ms=mem_duration,
                        generation_cost_usd=round(mem_cost / max(1, len(batch_memories)), 4),
                        batch_index=batch_idx,
                        symbolic_tags=[],
                    )
                    session.add(mem)

                    all_memories.append({
                        "time": mem_data.get("time", ""),
                        "content": content,
                        "strength": strength,
                    })
                    memory_count += 1

                # Save relationships + origin_story each batch (in case later batches fail)
                if ongoing_state and ongoing_state.get("relationships"):
                    robot.relationships_snapshot = ongoing_state["relationships"]
                if batch_idx == 0 and batch_memories:
                    robot.origin_story = batch_memories[0].get("content", "")[:500]

                await session.commit()

                job["memories_done"] = memory_count
                job["total_words"] = total_words

            job["current_memory"] = None
            elapsed_all = int((time.time() - t0_all) * 1000)
            _set_step(job, "memories", "done",
                      detail=f"{memory_count} 条碎片，{total_words:,} 字",
                      time_ms=elapsed_all, cost_usd=round(memories_cost, 4))

            # === 4. Portrait ===
            t0 = time.time()
            _set_step(job, "portrait", "running")

            sys_port, usr_port = build_portrait_prompt(
                robot_name=robot_name, robot_age=robot_age,
                object_description=description,
                personality=personality, core_desire=core_desire,
                core_fear=core_fear, life_theme=life_theme,
                all_memories_with_strength=all_memories,
            )
            portrait = await llm.generate_structured(
                messages=[{"role": "user", "content": usr_port}], system_prompt=sys_port,
            )
            stats = _get_llm_stats()
            _track()

            elapsed = int((time.time() - t0) * 1000)
            total_elapsed_ms = int((time.time() - gen_start) * 1000)

            robot.portrait = portrait
            robot.generation_stats = {
                "total_cost_usd": round(total_cost, 4),
                "total_time_ms": total_elapsed_ms,
                "total_words": total_words,
                "moment_count": memory_count,
            }
            await session.commit()

            _set_step(job, "portrait", "done", detail="画像完成",
                      time_ms=elapsed, cost_usd=stats["cost_usd"])

            job["portrait"] = portrait

            # === 5. Voice ===
            t0 = time.time()
            _set_step(job, "voice", "running")

            from app.api.tts import _get_voice_config
            voice_config = _get_voice_config(robot)

            elapsed = int((time.time() - t0) * 1000)
            voice_label = voice_config.get("voice", "").split("-")[-1].replace("Neural", "")

            _set_step(job, "voice", "done",
                      detail=f"声音：{voice_label}风格，已生成专属声纹",
                      time_ms=elapsed)

            total_elapsed_ms = int((time.time() - gen_start) * 1000)
            robot.generation_stats = {
                "status": "done",
                "total_cost_usd": round(total_cost, 4),
                "total_time_ms": total_elapsed_ms,
                "total_words": total_words,
                "moment_count": memory_count,
                "steps": job["steps"],
            }
            await session.commit()

            job["stats"] = robot.generation_stats
            job["robot"]["origin_story"] = robot.origin_story
            job["robot"]["created_at"] = robot.created_at.isoformat()
            job["status"] = "done"

    except Exception as e:
        import traceback
        traceback.print_exc()
        job["status"] = "error"
        job["error"] = str(e)

        # Mark robot as done in DB so detail page doesn't stay stuck
        if job.get("robot_db_id"):
            try:
                import uuid as _uuid
                async with async_session() as err_session:
                    result = await err_session.execute(
                        select(Robot).where(Robot.id == _uuid.UUID(job["robot_db_id"]))
                    )
                    r = result.scalar_one_or_none()
                    if r and r.generation_stats and r.generation_stats.get("status") == "creating":
                        r.generation_stats = {"status": "error", "error": str(e)}
                        await err_session.commit()
            except Exception:
                pass


def _set_step(job: dict, step_id: str, status: str, detail: str = "",
              time_ms: int = 0, cost_usd: float = 0.0, provider: str = ""):
    for step in job["steps"]:
        if step["id"] == step_id:
            step["status"] = status
            if detail:
                step["detail"] = detail
            if time_ms:
                step["time_ms"] = time_ms
            if cost_usd:
                step["cost_usd"] = cost_usd
            if provider:
                step["provider"] = provider
            break

    # Persist to DB if robot exists
    if job.get("robot_db_id"):
        import asyncio
        asyncio.ensure_future(_persist_job_to_db(job))


async def _persist_job_to_db(job: dict):
    """Save current job state to robot's generation_stats."""
    try:
        robot_id = job.get("robot_db_id")
        if not robot_id:
            return
        import uuid as _uuid
        async with async_session() as session:
            result = await session.execute(
                select(Robot).where(Robot.id == _uuid.UUID(robot_id))
            )
            robot = result.scalar_one_or_none()
            if robot:
                robot.generation_stats = {
                    "status": "creating",
                    "job_id": job.get("job_id", ""),
                    "steps": job["steps"],
                }
                await session.commit()
    except Exception:
        pass


@router.post("", response_model=list[RobotOut])
async def create_robots(body: RobotCreate, session: AsyncSession = Depends(get_session)):
    llm = get_llm()
    return await RobotService(session=session, llm=llm).create_robots(
        user_id=DEFAULT_USER_ID, count=body.count, preferences=body.preferences,
    )

@router.delete("/{robot_id}")
async def delete_robot(robot_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    """Delete a robot and all its memories."""
    from sqlalchemy import delete
    from app.db.models import YearlyMemory, Memory
    # Delete memories
    await session.execute(delete(YearlyMemory).where(YearlyMemory.robot_id == robot_id))
    await session.execute(delete(Memory).where(Memory.owner_id == robot_id))
    # Delete robot
    result = await session.execute(select(Robot).where(Robot.id == robot_id))
    robot = result.scalar_one_or_none()
    if not robot:
        raise HTTPException(status_code=404, detail="Robot not found")
    await session.delete(robot)
    await session.commit()
    return {"deleted": str(robot_id), "name": robot.name}


@router.delete("/activity/all")
async def clear_all_activity(session: AsyncSession = Depends(get_session)):
    """Delete all activity logs for all robots."""
    from sqlalchemy import delete as sa_delete
    from app.db.models import ActivityLog
    await session.execute(sa_delete(ActivityLog))
    await session.commit()
    return {"deleted": True}


@router.get("/{robot_id}/activity")
async def get_activity(
    robot_id: uuid.UUID,
    limit: int = 20,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
):
    """Get activity log for a robot."""
    from app.db.models import ActivityLog
    from sqlalchemy import func

    total = (await session.execute(
        select(func.count()).select_from(ActivityLog).where(ActivityLog.robot_id == robot_id)
    )).scalar_one()

    result = await session.execute(
        select(ActivityLog)
        .where(ActivityLog.robot_id == robot_id)
        .order_by(ActivityLog.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    logs = result.scalars().all()
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [
            {
                "id": str(log.id),
                "event_type": log.event_type,
                "content": log.content,
                "detail": log.detail,
                "created_at": log.created_at.isoformat(),
            }
            for log in logs
        ],
    }


@router.get("/{robot_id}/skills")
async def get_skills(robot_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    """Get all skills a robot has acquired."""
    from app.db.models import RobotSkill
    result = await session.execute(
        select(RobotSkill).where(RobotSkill.robot_id == robot_id)
        .order_by(RobotSkill.acquired_at)
    )
    skills = list(result.scalars().all())
    return [
        {
            "id": str(s.id),
            "name": s.name,
            "description": s.description,
            "trigger_keywords": s.trigger_keywords or [],
            "skill_type": s.skill_type,
            "usage_count": s.usage_count,
            "acquired_at": s.acquired_at.isoformat() if s.acquired_at else None,
            "last_used_at": s.last_used_at.isoformat() if s.last_used_at else None,
        }
        for s in skills
    ]


@router.get("/{robot_id}/memories")
async def get_memories(robot_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    """Get a robot's conversational memories (the self-iterating memory pyramid:
    principle / semantic / episodic), with utility & retrieval signals."""
    from app.db.models import Memory
    result = await session.execute(
        select(Memory)
        .where(Memory.owner_id == robot_id)
        .where(Memory.archived.is_(False))
        .order_by(Memory.importance_score.desc().nullslast())
    )
    mems = list(result.scalars().all())
    return [
        {
            "id": str(m.id),
            "layer": m.memory_layer or "episodic",
            "type": m.memory_type,
            "content": (m.summary or m.content or "")[:300],
            "importance": round(m.importance_score or 0.0, 2),
            "utility": round(m.utility_score or 0.0, 2),
            "retrieved": m.retrieved_count or 0,
            "useful": m.useful_count or 0,
            "source": m.memory_source,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in mems
    ]


@router.get("", response_model=list[RobotOut])
async def list_robots(desktop: bool | None = None, session: AsyncSession = Depends(get_session)):
    robots = await RobotService(session=session, llm=get_llm()).get_robots(DEFAULT_USER_ID)
    if desktop is not None:
        robots = [r for r in robots if r.desktop_visible == desktop]
    return robots

@router.patch("/{robot_id}", response_model=RobotOut)
async def update_robot(robot_id: uuid.UUID, body: dict, session: AsyncSession = Depends(get_session)):
    """Update specific robot fields (desktop_visible, voice_profile, etc.)"""
    from app.db.models import Robot
    result = await session.execute(select(Robot).where(Robot.id == robot_id))
    robot = result.scalar_one_or_none()
    if not robot:
        raise HTTPException(status_code=404, detail="Robot not found")
    allowed = {"desktop_visible", "voice_profile", "name"}
    for key, value in body.items():
        if key in allowed:
            setattr(robot, key, value)
    await session.commit()
    await session.refresh(robot)
    return robot


@router.get("/{robot_id}", response_model=RobotDetail)
async def get_robot(robot_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    robot = await RobotService(session=session, llm=get_llm()).get_robot_detail(robot_id)
    if not robot:
        raise HTTPException(status_code=404, detail="Robot not found")
    return robot
