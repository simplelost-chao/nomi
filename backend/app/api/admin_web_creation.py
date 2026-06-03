"""Create characters from web search — for known fictional characters."""
import asyncio
import json
import math
import uuid
from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.db.engine import async_session
from app.db.models import Robot, User, YearlyMemory
from app.prompts.creation import build_portrait_prompt

router = APIRouter(prefix="/api/admin", tags=["admin"])

DEFAULT_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

_web_creation_jobs: dict[str, dict] = {}


class WebCreateRequest(BaseModel):
    character_name: str
    source: str  # e.g. "葬送的芙莉莲"


@router.post("/characters/create-from-web")
async def create_from_web(req: WebCreateRequest):
    """Start async character creation from web search."""
    job_id = str(uuid.uuid4())[:8]
    _web_creation_jobs[job_id] = {
        "status": "searching",
        "character_name": req.character_name,
        "source": req.source,
        "progress": "开始搜索...",
        "robot_id": None,
    }
    asyncio.create_task(_run_web_creation(job_id, req.character_name, req.source))
    return {"job_id": job_id}


@router.get("/characters/create-from-web/status/{job_id}")
async def get_web_creation_status(job_id: str):
    """Check creation progress."""
    job = _web_creation_jobs.get(job_id)
    if not job:
        return JSONResponse({"error": "Job not found"}, status_code=404)
    return job


class BuildMemoriesRequest(BaseModel):
    source: str  # e.g. "葬送的芙莉莲"


@router.post("/characters/{char_id}/build-memories")
async def build_memories_for_existing(char_id: str, req: BuildMemoriesRequest):
    """Build memories from web search for an existing character."""
    async with async_session() as session:
        result = await session.execute(
            select(Robot).where(Robot.id == uuid.UUID(char_id))
        )
        robot = result.scalar_one_or_none()
        if not robot:
            return JSONResponse({"error": "Robot not found"}, status_code=404)

    job_id = str(uuid.uuid4())[:8]
    _web_creation_jobs[job_id] = {
        "status": "searching",
        "character_name": robot.name,
        "source": req.source,
        "progress": "开始搜索...",
        "robot_id": str(robot.id),
    }
    asyncio.create_task(
        _run_build_memories(job_id, robot.id, robot.name, req.source)
    )
    return {"job_id": job_id}


async def _run_build_memories(
    job_id: str, robot_id: uuid.UUID, character_name: str, source: str
):
    """Search web and generate memories + portrait for an existing character."""
    job = _web_creation_jobs[job_id]
    import time
    start_time = time.time()

    def elapsed():
        return f"（已用时 {int(time.time() - start_time)}s）"

    try:
        # Step 1: Search
        job["status"] = "searching"
        job["progress"] = "正在搜索角色资料..."

        search_queries = [
            f'"{character_name}" {source} 角色设定 性格 外貌',
            f'"{character_name}" {source} 经历 故事线 重要事件',
            f'"{character_name}" {source} 人物关系',
            f'"{character_name}" {source} 语录 说话风格 口头禅',
        ]

        search_prompts = [
            f"""请搜索以下内容，然后把你找到的所有相关信息原样整理输出（不要总结，尽量保留原始细节）：

搜索：{query}

把搜索到的所有相关内容都列出来，越详细越好。"""
            for query in search_queries
        ]

        search_tasks = [_claude_cli_search(prompt) for prompt in search_prompts]
        search_results = await asyncio.gather(*search_tasks, return_exceptions=True)

        combined_search = ""
        labels = ["角色设定/性格/外貌", "经历/故事线", "人物关系", "语录/说话风格"]
        for label, result in zip(labels, search_results):
            if isinstance(result, Exception):
                combined_search += f"\n\n=== {label} ===\n（搜索失败）"
            else:
                combined_search += f"\n\n=== {label} ===\n{result}"

        if not any(r for r in search_results if isinstance(r, str) and r.strip()):
            raise RuntimeError("所有搜索都没有返回结果")


        # Step 2: Load robot info from DB
        job["status"] = "memories"
        job["progress"] = f"搜索完成（{len(combined_search)}字资料），正在生成记忆碎片...这一步可能需要2-5分钟 {elapsed()}"

        async with async_session() as session:
            result = await session.execute(
                select(Robot).where(Robot.id == robot_id)
            )
            robot = result.scalar_one_or_none()
            if not robot:
                raise RuntimeError("角色不存在")

            robot_name = robot.name
            robot_age = robot.age or 20
            personality = robot.personality
            if isinstance(personality, dict):
                personality = personality.get("traits", [])
            core_desire = robot.core_desire or ""
            core_fear = robot.core_fear or ""
            origin_story = robot.origin_story or ""

            # Step 3: Generate memories
            memories_prompt = f"""你是「{robot_name}」，来自《{source}》。以下是关于你的搜索资料。

搜索资料：
{combined_search}

角色信息：
- 年龄：{robot_age}
- 性格：{json.dumps(personality, ensure_ascii=False) if personality else '未知'}
- 核心愿望：{core_desire}
- 核心恐惧：{core_fear}
- 背景：{origin_story}

请以第一人称「我」的视角，生成 20-60 条记忆碎片。覆盖你生命中的重要时刻。

每条记忆 80-250 字，是记忆碎片：一个画面、一种感觉、一句对话、一个瞬间。

请严格按以下 JSON 格式输出：
{{
  "memories": [
    {{
      "time": "时间描述",
      "approximate_age": 大约年龄数字,
      "title": "一句话标题",
      "emotional_core": "核心情感",
      "content": "80-250字的记忆碎片正文（第一人称）",
      "memory_type": "vivid/fragment/feeling",
      "importance": 0.0到1.0,
      "tags": ["标签1", "标签2"]
    }}
  ]
}}

直接输出 JSON。"""

            memories_result = await _claude_cli_generate(memories_prompt)
            memories_list = memories_result.get("memories", [])

            if not memories_list:
                raise RuntimeError("记忆生成失败")

            all_memories = []
            total_words = 0

            for mem_data in memories_list:
                content = mem_data.get("content", "")
                importance = mem_data.get("importance", 0.5)
                approx_age = mem_data.get("approximate_age", 0)
                years_ago = max(0, robot_age - approx_age)
                decay = math.exp(-0.08 * years_ago)
                strength = round(max(decay, importance * 0.7), 2)
                word_count = len(content)
                total_words += word_count

                mem = YearlyMemory(
                    robot_id=robot_id,
                    age=approx_age,
                    memory_title=mem_data.get("title", ""),
                    memory_content=content,
                    emotional_impact={"core": mem_data.get("emotional_core", "")},
                    memory_type=mem_data.get("memory_type", "fragment"),
                    importance=importance,
                    memory_strength=strength,
                    word_count=word_count,
                    generation_time_ms=0,
                    generation_cost_usd=0.0,
                    batch_index=0,
                    symbolic_tags=mem_data.get("tags", []),
                )
                session.add(mem)

                all_memories.append({
                    "time": mem_data.get("time", ""),
                    "content": content,
                    "strength": strength,
                })

            await session.commit()

            job["progress"] = f"已生成 {len(memories_list)} 条记忆（{total_words:,} 字），正在生成画像... {elapsed()}"
            job["memories_count"] = len(memories_list)

            # Step 4: Generate portrait
            job["status"] = "portrait"

            life_theme = f"{robot_name}的故事"
            sys_port, usr_port = build_portrait_prompt(
                robot_name=robot_name,
                robot_age=robot_age,
                object_description=f"来自《{source}》的角色「{robot_name}」。{origin_story[:200]}",
                personality=personality if isinstance(personality, list) else [],
                core_desire=core_desire,
                core_fear=core_fear,
                life_theme=life_theme,
                all_memories_with_strength=all_memories,
            )

            portrait = await _claude_cli_generate(f"{sys_port}\n\n{usr_port}")

            robot.portrait = portrait
            robot.generation_stats = {
                **(robot.generation_stats or {}),
                "memory_source": "web_search",
                "character_source": source,
                "memory_count": len(memories_list),
                "total_words": total_words,
            }
            await session.commit()

            job["status"] = "done"
            job["progress"] = "记忆构建完成！"

    except Exception as e:
        import traceback
        traceback.print_exc()
        job["status"] = "failed"
        job["progress"] = f"构建失败：{str(e)}"


async def _claude_cli_search(prompt: str) -> str:
    """Run a Claude CLI call with WebSearch tool and return the result text."""
    proc = await asyncio.create_subprocess_exec(
        "claude", "-p", prompt,
        "--output-format", "json",
        "--max-turns", "5",
        "--allowedTools", "WebSearch",
        "--permission-mode", "bypassPermissions",
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        print(f"[web_creation] Claude CLI search failed: {stderr.decode()[:300]}")
        return ""

    try:
        output = json.loads(stdout.decode())
        return output.get("result", "")
    except Exception as e:
        print(f"[web_creation] Parse search output error: {e}")
        return stdout.decode()


async def _claude_cli_generate(prompt: str, timeout_seconds: int = 300) -> dict:
    """Run a Claude CLI call (no tools) and return parsed JSON."""
    proc = await asyncio.create_subprocess_exec(
        "claude", "-p", prompt,
        "--output-format", "json",
        "--max-turns", "3",
        "--permission-mode", "bypassPermissions",
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"Claude CLI failed: {stderr.decode()[:300]}")

    output = json.loads(stdout.decode())
    result_text = output.get("result", "").strip()

    # Extract JSON from markdown code blocks if present
    if "```json" in result_text:
        result_text = result_text.split("```json", 1)[1].rsplit("```", 1)[0]
    elif "```" in result_text:
        result_text = result_text.split("```", 1)[1].rsplit("```", 1)[0]

    return json.loads(result_text.strip())


async def _run_web_creation(job_id: str, character_name: str, source: str):
    job = _web_creation_jobs[job_id]

    try:
        # === Step 1: Search ===
        job["status"] = "searching"
        job["progress"] = "正在搜索角色资料..."

        search_queries = [
            f'"{character_name}" {source} 角色设定 性格 外貌',
            f'"{character_name}" {source} 经历 故事线 重要事件',
            f'"{character_name}" {source} 人物关系',
            f'"{character_name}" {source} 语录 说话风格 口头禅',
        ]

        search_prompts = [
            f"""请搜索以下内容，然后把你找到的所有相关信息原样整理输出（不要总结，尽量保留原始细节）：

搜索：{query}

把搜索到的所有相关内容都列出来，越详细越好。"""
            for query in search_queries
        ]

        # Run all 4 searches concurrently
        search_tasks = [_claude_cli_search(prompt) for prompt in search_prompts]
        search_results = await asyncio.gather(*search_tasks, return_exceptions=True)

        combined_search = ""
        labels = ["角色设定/性格/外貌", "经历/故事线", "人物关系", "语录/说话风格"]
        for label, result in zip(labels, search_results):
            if isinstance(result, Exception):
                print(f"[web_creation] Search failed for {label}: {result}")
                combined_search += f"\n\n=== {label} ===\n（搜索失败）"
            else:
                combined_search += f"\n\n=== {label} ===\n{result}"

        if not any(r for r in search_results if isinstance(r, str) and r.strip()):
            raise RuntimeError("所有搜索都没有返回结果")


        job["progress"] = "搜索完成，正在生成角色档案..."

        # === Step 2: Synthesize profile ===
        job["status"] = "synthesizing"

        synthesis_prompt = f"""你是一个角色档案专家。根据以下搜索到的关于「{character_name}」（来自《{source}》）的资料，生成一份结构化的角色档案。

搜索资料：
{combined_search}

请严格按以下 JSON 格式输出（不要输出任何其他文字）：
{{
  "name": "{character_name}",
  "age": 角色的年龄（数字，如果是不老的角色就用外表年龄）,
  "birth_place": "出生地/来源地",
  "origin_story": "角色的背景故事概述（200-500字，第三人称）",
  "core_desire": "核心愿望（一句话）",
  "core_fear": "核心恐惧（一句话）",
  "personality": ["性格特征1", "性格特征2", "性格特征3", "性格特征4", "性格特征5"],
  "speaking_style": {{
    "speed": "slow/medium/fast",
    "tone": "soft/bright/deep/playful/cold/warm",
    "sentence_length": "short/medium/long",
    "metaphor_level": "low/medium/high",
    "catchphrases": ["口头禅1", "口头禅2"],
    "speech_patterns": ["说话习惯1", "说话习惯2"]
  }},
  "voice_profile": {{
    "gender_feeling": "neutral/male/female/neutral-female/neutral-male",
    "age_feeling": "child/young/mature",
    "pitch": "low/medium/high/soft",
    "emotion_range": "warm/cool/wide/narrow"
  }},
  "system_prompt": "你是{character_name}，来自《{source}》。（200-400字的角色扮演系统提示，包含性格特点、说话方式、行为准则。用第二人称'你'来描述角色）"
}}"""

        profile = await _claude_cli_generate(synthesis_prompt)
        job["progress"] = "角色档案生成完成，正在创建角色..."

        # === Step 3: Create Robot record ===
        job["status"] = "creating"

        robot_name = profile.get("name", character_name)
        robot_age = profile.get("age", 20)
        personality = profile.get("personality", [])
        core_desire = profile.get("core_desire", "")
        core_fear = profile.get("core_fear", "")
        birth_place = profile.get("birth_place", "")
        origin_story = profile.get("origin_story", "")
        speaking_style = profile.get("speaking_style", {})
        voice_profile = profile.get("voice_profile", {})
        system_prompt = profile.get("system_prompt", "")

        async with async_session() as session:
            # Ensure user exists
            result = await session.execute(select(User).where(User.id == DEFAULT_USER_ID))
            if not result.scalar_one_or_none():
                session.add(User(id=DEFAULT_USER_ID))
                await session.commit()

            robot = Robot(
                user_id=DEFAULT_USER_ID,
                name=robot_name,
                age=robot_age,
                birth_place=birth_place,
                origin_story=origin_story,
                core_desire=core_desire,
                core_fear=core_fear,
                personality=personality,
                speaking_style=speaking_style,
                voice_profile=voice_profile,
                system_prompt=system_prompt,
                current_emotion={"emotion": "calm", "intensity": 0.3},
                energy=100.0,
                generation_stats={"source": "web_search", "status": "creating"},
            )
            session.add(robot)
            await session.commit()
            await session.refresh(robot)

            robot_id = str(robot.id)
            job["robot_id"] = robot_id
            job["progress"] = "角色已创建，正在生成记忆碎片..."

            # === Step 4: Generate memories ===
            job["status"] = "memories"

            memories_prompt = f"""你是「{robot_name}」，来自《{source}》。以下是关于你的搜索资料和角色档案。

搜索资料：
{combined_search}

角色档案：
- 年龄：{robot_age}
- 性格：{json.dumps(personality, ensure_ascii=False)}
- 核心愿望：{core_desire}
- 核心恐惧：{core_fear}
- 背景：{origin_story}

请以第一人称「我」的视角，生成 20-60 条记忆碎片。这些记忆应该覆盖你生命中的重要时刻，从最早的记忆到最近的经历。

每条记忆 80-250 字，应该是记忆碎片而不是完整叙事：
- 一个画面、一种感觉、一句对话、一个瞬间
- 要有情感色彩，体现你的性格
- 覆盖不同时期和不同类型的经历（日常、战斗、关系、成长、失去、领悟等）

请严格按以下 JSON 格式输出：
{{
  "memories": [
    {{
      "time": "时间描述（如'很久以前'、'刚认识他的时候'、'那个冬天'）",
      "approximate_age": 大约年龄数字,
      "title": "一句话标题",
      "emotional_core": "核心情感（如'温暖'、'失落'、'释然'）",
      "content": "80-250字的记忆碎片正文（第一人称'我'）",
      "memory_type": "vivid/fragment/feeling",
      "importance": 0.0到1.0之间的数字,
      "tags": ["标签1", "标签2"]
    }}
  ]
}}

memory_type 说明：
- vivid：清晰的画面，有细节
- fragment：只是一个瞬间
- feeling：一段时期的感受

请生成 30-50 条记忆，覆盖角色生命中的各个阶段。直接输出 JSON。"""

            memories_result = await _claude_cli_generate(memories_prompt)
            memories_list = memories_result.get("memories", [])

            if not memories_list:
                raise RuntimeError("记忆生成失败：没有返回任何记忆")

            all_memories = []
            total_words = 0

            for idx, mem_data in enumerate(memories_list):
                content = mem_data.get("content", "")
                importance = mem_data.get("importance", 0.5)
                approx_age = mem_data.get("approximate_age", 0)
                years_ago = max(0, robot_age - approx_age)
                decay = math.exp(-0.08 * years_ago)
                strength = round(max(decay, importance * 0.7), 2)
                word_count = len(content)
                total_words += word_count

                mem = YearlyMemory(
                    robot_id=robot.id,
                    age=approx_age,
                    memory_title=mem_data.get("title", ""),
                    memory_content=content,
                    emotional_impact={"core": mem_data.get("emotional_core", "")},
                    memory_type=mem_data.get("memory_type", "fragment"),
                    importance=importance,
                    memory_strength=strength,
                    word_count=word_count,
                    generation_time_ms=0,
                    generation_cost_usd=0.0,
                    batch_index=0,
                    symbolic_tags=mem_data.get("tags", []),
                )
                session.add(mem)

                all_memories.append({
                    "time": mem_data.get("time", ""),
                    "content": content,
                    "strength": strength,
                })

            await session.commit()

            job["progress"] = f"已生成 {len(memories_list)} 条记忆（{total_words:,} 字），正在生成画像..."
            job["memories_count"] = len(memories_list)
            job["total_words"] = total_words

            # === Step 5: Generate portrait ===
            job["status"] = "portrait"

            # Derive life_theme from origin_story
            life_theme = f"{robot_name}的故事"

            sys_port, usr_port = build_portrait_prompt(
                robot_name=robot_name,
                robot_age=robot_age,
                object_description=f"来自《{source}》的角色「{robot_name}」。{origin_story[:200]}",
                personality=personality,
                core_desire=core_desire,
                core_fear=core_fear,
                life_theme=life_theme,
                all_memories_with_strength=all_memories,
            )

            # Use Claude CLI for portrait generation
            portrait_prompt = f"""{sys_port}

{usr_port}"""
            portrait = await _claude_cli_generate(portrait_prompt)

            robot.portrait = portrait
            robot.generation_stats = {
                "source": "web_search",
                "status": "done",
                "character_source": source,
                "memory_count": len(memories_list),
                "total_words": total_words,
            }
            await session.commit()

            job["status"] = "done"
            job["progress"] = "创建完成！"
            job["portrait"] = portrait

    except Exception as e:
        import traceback
        traceback.print_exc()
        job["status"] = "failed"
        job["progress"] = f"创建失败：{str(e)}"
        job["error"] = str(e)

        # Update robot status in DB if it was created
        if job.get("robot_id"):
            try:
                async with async_session() as err_session:
                    result = await err_session.execute(
                        select(Robot).where(Robot.id == uuid.UUID(job["robot_id"]))
                    )
                    r = result.scalar_one_or_none()
                    if r and r.generation_stats and r.generation_stats.get("status") == "creating":
                        r.generation_stats = {
                            "source": "web_search",
                            "status": "failed",
                            "error": str(e),
                        }
                        await err_session.commit()
            except Exception:
                pass
