# Admin Panel Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the existing `admin_panel.html` with character detail pages, image/voice version management, memory timeline display, and a new "create from web search" character creation mode.

**Architecture:** Single-file HTML frontend (`admin_panel.html`) with vanilla JS, communicating with FastAPI backend (`admin.py`). New `asset_versions` database table for version tracking. New `admin_web_creation.py` for web-based character creation. Files stored on local filesystem with `versions/` subdirectories.

**Tech Stack:** FastAPI (Python), SQLAlchemy + Alembic (PostgreSQL), vanilla HTML/CSS/JS, Gemini Imagen API, Claude CLI (web search + LLM)

---

## File Structure

### Files to Create
- `backend/alembic/versions/<auto>_add_asset_versions_table.py` — Alembic migration for `asset_versions` table
- `backend/app/api/admin_web_creation.py` — Web search character creation endpoint + async job logic

### Files to Modify
- `backend/app/db/models.py` — Add `AssetVersion` model
- `backend/app/api/admin.py` — Add version management endpoints, memories endpoint, modify `generate_images` to auto-save versions
- `backend/app/admin_panel.html` — Complete UI rewrite: list → detail navigation, version history, memory timeline, two creation modes
- `backend/app/main.py` — Register new router for `admin_web_creation`

---

### Task 1: Add `AssetVersion` Database Model + Migration

**Files:**
- Modify: `backend/app/db/models.py`
- Create: `backend/alembic/versions/<auto>_add_asset_versions_table.py`

- [ ] **Step 1: Add AssetVersion model to models.py**

Add after the `Robot` class (around line 88, before `YearlyMemory`):

```python
class AssetVersion(Base):
    __tablename__ = "asset_versions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    robot_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("robots.id"))
    asset_type: Mapped[str] = mapped_column(Text, nullable=False)  # 'image' | 'voice_config'
    asset_key: Mapped[str] = mapped_column(Text, nullable=False)  # state name or 'voice_profile'
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    file_path: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB_TYPE)
    is_current: Mapped[bool] = mapped_column(default=False)
    is_starred: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)
```

- [ ] **Step 2: Generate Alembic migration**

```bash
cd /Users/chao/Documents/Projects/nomi/backend && alembic revision --autogenerate -m "add_asset_versions_table"
```

Expected: New migration file created in `backend/alembic/versions/`.

- [ ] **Step 3: Apply migration**

```bash
cd /Users/chao/Documents/Projects/nomi/backend && alembic upgrade head
```

Expected: `asset_versions` table created in database.

- [ ] **Step 4: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/*asset_versions*
git commit -m "feat(admin): add AssetVersion model and migration"
```

---

### Task 2: Version Management Backend APIs

**Files:**
- Modify: `backend/app/api/admin.py`

- [ ] **Step 1: Add imports and helper function for version saving**

At the top of `admin.py`, add the `AssetVersion` import and a helper:

```python
from app.db.models import Robot, AssetVersion
```

Add a helper function after the existing helpers at the bottom of `admin.py`:

```python
async def _save_version(robot_id: uuid.UUID, asset_type: str, asset_key: str,
                        file_path: str, metadata: dict | None = None):
    """Save a new version record and return the version number."""
    async with async_session() as session:
        # Find next version number
        from sqlalchemy import func
        result = await session.execute(
            select(func.coalesce(func.max(AssetVersion.version_number), 0))
            .where(AssetVersion.robot_id == robot_id)
            .where(AssetVersion.asset_type == asset_type)
            .where(AssetVersion.asset_key == asset_key)
        )
        next_version = result.scalar() + 1

        # Unset current flag on previous versions
        from sqlalchemy import update
        await session.execute(
            update(AssetVersion)
            .where(AssetVersion.robot_id == robot_id)
            .where(AssetVersion.asset_type == asset_type)
            .where(AssetVersion.asset_key == asset_key)
            .values(is_current=False)
        )

        version = AssetVersion(
            id=uuid.uuid4(),
            robot_id=robot_id,
            asset_type=asset_type,
            asset_key=asset_key,
            version_number=next_version,
            file_path=file_path,
            metadata_=metadata,
            is_current=True,
        )
        session.add(version)
        await session.commit()
        return next_version
```

- [ ] **Step 2: Modify `generate_images` to auto-save versions**

In the `generate_images` function, after `img_data` is received and before writing to `{state}.png`, archive the current file and save a version record. Replace the image-saving block (lines 91-101) with:

```python
    for state, prompt in prompts_dict.items():
        full_prompt = f"{base_prompt} {prompt}"
        try:
            img_data = _call_imagen(full_prompt)
            if img_data:
                path = os.path.join(char_dir, f"{state}.png")
                # Archive current file if it exists
                versions_dir = os.path.join(char_dir, "versions")
                os.makedirs(versions_dir, exist_ok=True)
                if os.path.exists(path):
                    from datetime import datetime as dt
                    ts = dt.now().strftime("%Y%m%d_%H%M%S")
                    # Determine next version number from DB
                    next_v = await _save_version(
                        robot_id=uuid.UUID(char_id),
                        asset_type="image",
                        asset_key=state,
                        file_path=f"versions/{state}_v{{pending}}_{ts}.png",
                        metadata={"prompt": full_prompt, "archived_from": "generate"},
                    )
                    archive_name = f"{state}_v{next_v - 1}_{ts}.png"
                    archive_path = os.path.join(versions_dir, archive_name)
                    os.rename(path, archive_path)
                    # Update the file_path on the version record we just created
                    # (the one marking the OLD file, which was previously current)
                    # Actually, we need to fix the logic: archive the old version,
                    # then save the NEW one as current.
                    # Let's simplify: save old to archive, then save new as current version.
                    async with async_session() as session:
                        from sqlalchemy import update
                        await session.execute(
                            update(AssetVersion)
                            .where(AssetVersion.robot_id == uuid.UUID(char_id))
                            .where(AssetVersion.asset_type == "image")
                            .where(AssetVersion.asset_key == state)
                            .where(AssetVersion.is_current == True)
                            .values(file_path=f"versions/{archive_name}", is_current=False)
                        )
                        await session.commit()

                # Write new image
                with open(path, "wb") as f:
                    f.write(img_data)

                # Save new version as current
                await _save_version(
                    robot_id=uuid.UUID(char_id),
                    asset_type="image",
                    asset_key=state,
                    file_path=f"{state}.png",
                    metadata={"prompt": full_prompt, "base_prompt": base_prompt, "state_prompt": prompt},
                )

                results[state] = {"ok": True, "size": len(img_data)}
            else:
                results[state] = {"ok": False, "error": "No image returned"}
        except Exception as e:
            results[state] = {"ok": False, "error": str(e)}
```

Note: This is the core logic but the exact implementation should be cleaned up — the key flow is:
1. If old file exists → rename to `versions/{state}_v{N}_{timestamp}.png`, update old version record
2. Write new file to `{state}.png`
3. Create new version record with `is_current=True`

- [ ] **Step 3: Add version list endpoint**

```python
@router.get("/characters/{char_id}/versions")
async def list_versions(char_id: str, asset_type: str = "image", asset_key: str = ""):
    """List all versions of a specific asset."""
    query = (
        select(AssetVersion)
        .where(AssetVersion.robot_id == uuid.UUID(char_id))
        .where(AssetVersion.asset_type == asset_type)
    )
    if asset_key:
        query = query.where(AssetVersion.asset_key == asset_key)
    query = query.order_by(AssetVersion.version_number.desc())

    async with async_session() as session:
        result = await session.execute(query)
        versions = result.scalars().all()

    return [
        {
            "id": str(v.id),
            "asset_type": v.asset_type,
            "asset_key": v.asset_key,
            "version_number": v.version_number,
            "file_path": v.file_path,
            "metadata": v.metadata_,
            "is_current": v.is_current,
            "is_starred": v.is_starred,
            "created_at": v.created_at.isoformat(),
        }
        for v in versions
    ]
```

- [ ] **Step 4: Add activate version endpoint**

```python
@router.post("/characters/{char_id}/versions/{version_id}/activate")
async def activate_version(char_id: str, version_id: str):
    """Switch to a specific version (copy version file to current)."""
    async with async_session() as session:
        result = await session.execute(
            select(AssetVersion).where(AssetVersion.id == uuid.UUID(version_id))
        )
        version = result.scalar_one_or_none()
        if not version:
            return JSONResponse({"error": "Version not found"}, status_code=404)

        robot_result = await session.execute(
            select(Robot).where(Robot.id == uuid.UUID(char_id))
        )
        robot = robot_result.scalar_one_or_none()
        if not robot:
            return JSONResponse({"error": "Robot not found"}, status_code=404)

    char_dir = _get_char_dir(robot.name)
    version_file = os.path.join(char_dir, version.file_path)
    current_file = os.path.join(char_dir, f"{version.asset_key}.png")

    if not os.path.exists(version_file):
        return JSONResponse({"error": "Version file missing"}, status_code=404)

    import shutil
    shutil.copy2(version_file, current_file)

    # Update is_current flags
    async with async_session() as session:
        from sqlalchemy import update
        await session.execute(
            update(AssetVersion)
            .where(AssetVersion.robot_id == uuid.UUID(char_id))
            .where(AssetVersion.asset_type == version.asset_type)
            .where(AssetVersion.asset_key == version.asset_key)
            .values(is_current=False)
        )
        await session.execute(
            update(AssetVersion)
            .where(AssetVersion.id == uuid.UUID(version_id))
            .values(is_current=True)
        )
        await session.commit()

    return {"activated": version.version_number}
```

- [ ] **Step 5: Add star toggle endpoint**

```python
@router.post("/characters/{char_id}/versions/{version_id}/star")
async def toggle_star(char_id: str, version_id: str):
    """Toggle star on a version."""
    async with async_session() as session:
        result = await session.execute(
            select(AssetVersion).where(AssetVersion.id == uuid.UUID(version_id))
        )
        version = result.scalar_one_or_none()
        if not version:
            return JSONResponse({"error": "Version not found"}, status_code=404)
        version.is_starred = not version.is_starred
        await session.commit()
        return {"is_starred": version.is_starred}
```

- [ ] **Step 6: Add version file serving endpoint**

```python
@router.get("/characters/{char_id}/versions/{version_id}/file")
async def get_version_file(char_id: str, version_id: str):
    """Serve a version's image file."""
    async with async_session() as session:
        result = await session.execute(
            select(AssetVersion).where(AssetVersion.id == uuid.UUID(version_id))
        )
        version = result.scalar_one_or_none()
        if not version:
            return JSONResponse({"error": "Version not found"}, status_code=404)

        robot_result = await session.execute(
            select(Robot).where(Robot.id == uuid.UUID(char_id))
        )
        robot = robot_result.scalar_one_or_none()

    char_dir = _get_char_dir(robot.name)
    file_path = os.path.join(char_dir, version.file_path)
    if not os.path.exists(file_path):
        return JSONResponse({"error": "File not found"}, status_code=404)

    with open(file_path, "rb") as f:
        data = f.read()
    from fastapi.responses import Response
    return Response(content=data, media_type="image/png")
```

- [ ] **Step 7: Add memories endpoint**

```python
@router.get("/characters/{char_id}/memories")
async def list_memories(char_id: str):
    """Get all yearly memories for a character, ordered by age."""
    from app.db.models import YearlyMemory
    async with async_session() as session:
        result = await session.execute(
            select(YearlyMemory)
            .where(YearlyMemory.robot_id == uuid.UUID(char_id))
            .order_by(YearlyMemory.age, YearlyMemory.batch_index)
        )
        memories = result.scalars().all()

    return [
        {
            "id": str(m.id),
            "age": m.age,
            "title": m.memory_title,
            "content": m.memory_content,
            "memory_type": m.memory_type,
            "importance": m.importance,
            "strength": m.memory_strength,
            "emotional_impact": m.emotional_impact,
            "symbolic_tags": m.symbolic_tags,
        }
        for m in memories
    ]
```

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/admin.py
git commit -m "feat(admin): version management APIs and memories endpoint"
```

---

### Task 3: Web Search Character Creation Backend

**Files:**
- Create: `backend/app/api/admin_web_creation.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Create `admin_web_creation.py` with job tracking and search logic**

```python
"""Create characters from web search — for known fictional characters."""
import asyncio
import json
import uuid
from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.db.engine import async_session
from app.db.models import Robot, YearlyMemory

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


async def _run_web_creation(job_id: str, character_name: str, source: str):
    """Full async pipeline: search → synthesize personality → generate memories."""
    job = _web_creation_jobs[job_id]
    try:
        # Step 1: Web search for character info
        job["status"] = "searching"
        job["progress"] = f"搜索「{character_name}」的信息..."

        search_queries = [
            f"{character_name} {source} 角色设定 性格 外貌",
            f"{character_name} {source} 经历 故事线 重要事件",
            f"{character_name} {source} 人物关系",
            f"{character_name} {source} 语录 说话风格 口头禅",
        ]

        all_search_results = []
        for i, query in enumerate(search_queries):
            job["progress"] = f"搜索中 ({i+1}/{len(search_queries)}): {query[:30]}..."
            result = await _web_search_raw(query)
            if result:
                all_search_results.append(result)

        if not all_search_results:
            job["status"] = "failed"
            job["progress"] = "搜索未找到相关信息"
            return

        combined_search = "\n\n---\n\n".join(all_search_results)

        # Step 2: LLM synthesizes character profile
        job["status"] = "synthesizing"
        job["progress"] = "整理角色资料，生成性格档案..."

        profile = await _synthesize_profile(character_name, source, combined_search)
        if not profile:
            job["status"] = "failed"
            job["progress"] = "无法生成角色档案"
            return

        # Step 3: Create Robot record
        job["status"] = "creating"
        job["progress"] = "创建角色记录..."

        async with async_session() as session:
            existing = await session.execute(select(Robot).where(Robot.name == character_name))
            if existing.scalar_one_or_none():
                job["status"] = "failed"
                job["progress"] = f"角色「{character_name}」已存在"
                return

            robot = Robot(
                id=uuid.uuid4(),
                user_id=DEFAULT_USER_ID,
                name=profile.get("name", character_name),
                age=profile.get("age"),
                birth_place=profile.get("birth_place", ""),
                origin_story=profile.get("origin_story", ""),
                core_desire=profile.get("core_desire", ""),
                core_fear=profile.get("core_fear", ""),
                personality=profile.get("personality", {}),
                speaking_style=profile.get("speaking_style", {}),
                voice_profile=profile.get("voice_profile", {}),
                system_prompt=profile.get("system_prompt", ""),
                generation_stats={"source": "web_search", "status": "creating"},
            )
            session.add(robot)
            await session.commit()
            robot_id = robot.id

        job["robot_id"] = str(robot_id)

        # Step 4: Generate memories from search results
        job["status"] = "generating_memories"
        job["progress"] = "生成角色记忆..."

        memories = await _generate_memories_from_web(
            character_name, source, combined_search, profile
        )

        async with async_session() as session:
            for i, mem in enumerate(memories):
                ym = YearlyMemory(
                    id=uuid.uuid4(),
                    robot_id=robot_id,
                    age=mem.get("approximate_age", 0),
                    memory_title=mem.get("title", ""),
                    memory_content=mem.get("content", ""),
                    emotional_impact={"core": mem.get("emotional_core", "")},
                    memory_type=mem.get("memory_type", "vivid"),
                    importance=mem.get("importance", 0.5),
                    memory_strength=mem.get("importance", 0.5),
                    symbolic_tags=mem.get("tags", []),
                    word_count=len(mem.get("content", "")),
                    batch_index=0,
                )
                session.add(ym)
            await session.commit()

        # Step 5: Generate portrait
        job["status"] = "portrait"
        job["progress"] = "生成人格画像..."
        await _generate_portrait(robot_id, character_name, profile, memories)

        job["status"] = "completed"
        job["progress"] = f"角色「{character_name}」创建完成！"

    except Exception as e:
        job["status"] = "failed"
        job["progress"] = f"创建失败: {str(e)}"


async def _web_search_raw(query: str) -> str | None:
    """Use Claude CLI with WebSearch tool to search and return raw text."""
    prompt = f"""请用 WebSearch 搜索「{query}」，然后将搜索到的所有相关内容原文整理输出。
不要总结，不要加自己的评论，只输出搜索到的原始信息。尽可能保留细节。"""

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
        return None

    try:
        output = json.loads(stdout.decode())
        return output.get("result", "").strip()
    except Exception:
        return None


async def _synthesize_profile(name: str, source: str, search_data: str) -> dict | None:
    """Use Claude to synthesize a character profile from search results."""
    prompt = f"""你是一个角色档案生成器。根据以下搜索到的关于「{name}」（来自《{source}》）的信息，生成一份完整的角色档案。

搜索结果：
{search_data[:8000]}

请用以下 JSON 格式输出（直接输出 JSON，不要其他文字）：
{{
  "name": "{name}",
  "age": 年龄数字（根据角色设定），
  "birth_place": "出生地/来源",
  "origin_story": "完整的背景故事（200-500字）",
  "core_desire": "核心愿望",
  "core_fear": "核心恐惧",
  "personality": {{
    "traits": ["性格特征1", "性格特征2", "性格特征3", "性格特征4", "性格特征5"]
  }},
  "speaking_style": {{
    "speed": "slow/medium/fast",
    "tone": "描述语气特点",
    "sentence_length": "short/medium/long",
    "metaphor_level": "low/medium/high",
    "catchphrases": ["口头禅1", "口头禅2"],
    "speech_patterns": "说话方式的详细描述（50-100字）"
  }},
  "voice_profile": {{
    "gender_feeling": "male/female/neutral",
    "age_feeling": "child/young/mature/old",
    "pitch": "low/medium/high",
    "emotion_range": "描述情感范围"
  }},
  "system_prompt": "用于对话的系统提示词（200-400字，描述角色身份、性格、说话方式、背景，让 AI 能扮演这个角色）"
}}"""

    proc = await asyncio.create_subprocess_exec(
        "claude", "-p", prompt,
        "--output-format", "json",
        "--max-turns", "2",
        "--permission-mode", "bypassPermissions",
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        return None

    try:
        output = json.loads(stdout.decode())
        result_text = output.get("result", "").strip()
        if "```json" in result_text:
            result_text = result_text.split("```json", 1)[1].rsplit("```", 1)[0]
        elif "```" in result_text:
            result_text = result_text.split("```", 1)[1].rsplit("```", 1)[0]
        return json.loads(result_text.strip())
    except Exception:
        return None


async def _generate_memories_from_web(
    name: str, source: str, search_data: str, profile: dict
) -> list[dict]:
    """Generate structured memories from web search data."""
    age = profile.get("age", 20)
    personality = profile.get("personality", {}).get("traits", [])

    prompt = f"""你是「{name}」，来自《{source}》。

你的性格：{personality}
你的年龄：{age}
你的背景：{profile.get('origin_story', '')}

以下是关于你的经历的资料：
{search_data[:6000]}

请根据这些资料，以第一人称回忆你人生中的重要时刻。
生成 20-60 条记忆碎片，按时间顺序排列。

每条记忆 80-250 字，是记忆碎片而不是叙事。要像在回忆：
- 一个画面："那天下着雨，我站在门口..."
- 一种感觉："那段时间我总觉得..."
- 一个瞬间："他说了那句话的时候..."

用 JSON 格式输出：
{{
  "memories": [
    {{
      "time": "模糊的时间描述",
      "approximate_age": 大约年龄,
      "title": "一句话标题",
      "emotional_core": "核心情感",
      "content": "80-250字的记忆碎片（第一人称）",
      "memory_type": "vivid/fragment/feeling",
      "importance": 0.0-1.0,
      "tags": ["标签1", "标签2"]
    }}
  ]
}}

直接输出 JSON。"""

    proc = await asyncio.create_subprocess_exec(
        "claude", "-p", prompt,
        "--output-format", "json",
        "--max-turns", "2",
        "--permission-mode", "bypassPermissions",
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        return []

    try:
        output = json.loads(stdout.decode())
        result_text = output.get("result", "").strip()
        if "```json" in result_text:
            result_text = result_text.split("```json", 1)[1].rsplit("```", 1)[0]
        elif "```" in result_text:
            result_text = result_text.split("```", 1)[1].rsplit("```", 1)[0]
        data = json.loads(result_text.strip())
        return data.get("memories", [])
    except Exception:
        return []


async def _generate_portrait(robot_id: uuid.UUID, name: str, profile: dict, memories: list[dict]):
    """Generate and save portrait using existing prompt builder."""
    from app.prompts.creation import build_portrait_prompt

    personality = profile.get("personality", {}).get("traits", [])
    memories_with_strength = [
        {
            "time": m.get("time", ""),
            "content": m.get("content", ""),
            "strength": m.get("importance", 0.5),
        }
        for m in memories
    ]

    system, user_msg = build_portrait_prompt(
        robot_name=name,
        robot_age=profile.get("age", 20),
        object_description=profile.get("origin_story", ""),
        personality=personality,
        core_desire=profile.get("core_desire", ""),
        core_fear=profile.get("core_fear", ""),
        life_theme=f"{name}的人生",
        all_memories_with_strength=memories_with_strength,
    )

    prompt = f"{system}\n\n{user_msg}"
    proc = await asyncio.create_subprocess_exec(
        "claude", "-p", prompt,
        "--output-format", "json",
        "--max-turns", "2",
        "--permission-mode", "bypassPermissions",
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        return

    try:
        output = json.loads(stdout.decode())
        result_text = output.get("result", "").strip()
        if "```json" in result_text:
            result_text = result_text.split("```json", 1)[1].rsplit("```", 1)[0]
        elif "```" in result_text:
            result_text = result_text.split("```", 1)[1].rsplit("```", 1)[0]
        portrait = json.loads(result_text.strip())

        async with async_session() as session:
            result = await session.execute(select(Robot).where(Robot.id == robot_id))
            robot = result.scalar_one_or_none()
            if robot:
                robot.portrait = portrait
                robot.generation_stats = {"source": "web_search", "status": "completed"}
                await session.commit()
    except Exception:
        pass
```

- [ ] **Step 2: Register the new router in main.py**

In `backend/app/main.py`, find where `admin.router` is included and add after it:

```python
from app.api.admin_web_creation import router as admin_web_creation_router
app.include_router(admin_web_creation_router)
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/admin_web_creation.py backend/app/main.py
git commit -m "feat(admin): web search character creation backend"
```

---

### Task 4: Admin Panel HTML — Page Structure and Navigation

**Files:**
- Modify: `backend/app/admin_panel.html`

This is the full rewrite of the HTML page. Split into sub-steps for clarity.

- [ ] **Step 1: Replace the HTML structure**

Replace the entire `<body>` content (everything inside `<body>...</body>`, keeping the existing `<style>` block for now) with the new page structure that supports list → detail navigation:

```html
<div class="header">
  <h1 id="pageTitle">Nomi 角色管理后台</h1>
  <span class="badge">Admin Panel</span>
  <div style="flex:1"></div>
  <button class="btn btn-primary" onclick="showCreateModal()" id="createBtn">+ 创建角色</button>
</div>

<div class="container">
  <!-- Page: Character List -->
  <div id="page-list">
    <div class="char-grid" id="charGrid"></div>
  </div>

  <!-- Page: Character Detail -->
  <div id="page-detail" style="display:none;">
    <div style="margin-bottom:20px;">
      <button class="btn btn-secondary" onclick="showList()">← 返回列表</button>
      <span id="detailName" style="font-size:20px; font-weight:600; margin-left:12px;"></span>
    </div>

    <!-- Section tabs within detail page -->
    <div class="tabs" id="detailTabs">
      <div class="tab active" onclick="switchDetailTab('info')">基本信息</div>
      <div class="tab" onclick="switchDetailTab('images')">表情图片</div>
      <div class="tab" onclick="switchDetailTab('voice')">语音</div>
      <div class="tab" onclick="switchDetailTab('memories')">记忆</div>
    </div>

    <div id="detail-info" class="detail-panel active"></div>
    <div id="detail-images" class="detail-panel"></div>
    <div id="detail-voice" class="detail-panel"></div>
    <div id="detail-memories" class="detail-panel"></div>
  </div>
</div>

<!-- Create Character Modal (supports two modes) -->
<div class="modal-overlay" id="createModal">
  <div class="modal">
    <div class="modal-header">
      <h2>创建角色</h2>
      <button class="modal-close" onclick="closeCreateModal()">✕</button>
    </div>
    <div class="modal-body">
      <div class="tabs" style="margin-bottom:16px;">
        <div class="tab active" onclick="switchCreateMode('manual')">手动创建</div>
        <div class="tab" onclick="switchCreateMode('web')">从网络构建</div>
      </div>

      <!-- Manual creation form -->
      <div id="create-manual">
        <div class="form-group">
          <label>角色名称</label>
          <input id="newName" placeholder="例：冯宝宝">
        </div>
        <div class="form-group">
          <label>目录名（英文）</label>
          <input id="newDirName" placeholder="例：fengbaobao">
        </div>
        <div class="form-group">
          <label>背景故事</label>
          <textarea id="newStory" placeholder="角色的来历和背景..."></textarea>
        </div>
        <div class="form-group">
          <label>性格特征（JSON）</label>
          <input id="newPersonality" placeholder='{"traits": ["天真", "野性"]}'>
        </div>
        <div class="form-group">
          <label>系统提示词</label>
          <textarea id="newPrompt" style="min-height:200px;"></textarea>
        </div>
        <button class="btn btn-primary" onclick="createCharacter()">创建</button>
        <div id="createResult" style="margin-top:12px;"></div>
      </div>

      <!-- Web search creation form -->
      <div id="create-web" style="display:none;">
        <div class="form-group">
          <label>角色名称</label>
          <input id="webCharName" placeholder="例：芙莉莲">
        </div>
        <div class="form-group">
          <label>来源作品</label>
          <input id="webSource" placeholder="例：葬送的芙莉莲">
        </div>
        <button class="btn btn-primary" onclick="createFromWeb()">开始构建</button>
        <div id="webCreateLog" class="log" style="display:none;"></div>
      </div>
    </div>
  </div>
</div>

<!-- Version History Modal -->
<div class="modal-overlay" id="versionModal">
  <div class="modal">
    <div class="modal-header">
      <h2 id="versionModalTitle">版本历史</h2>
      <button class="modal-close" onclick="closeVersionModal()">✕</button>
    </div>
    <div class="modal-body" id="versionModalBody"></div>
  </div>
</div>
```

- [ ] **Step 2: Add new CSS styles**

Add these styles inside the existing `<style>` block, after the existing styles:

```css
/* Detail page */
.detail-panel { display:none; }
.detail-panel.active { display:block; }

/* Info section */
.info-grid { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
.info-block { background:#1a1a2e; border:1px solid #2a2a4a; border-radius:12px; padding:16px; }
.info-block label { font-size:12px; color:#888; display:block; margin-bottom:4px; }
.info-block .value { font-size:14px; line-height:1.6; }

/* Image grid with version badge */
.img-state-card { background:#1a1a2e; border:1px solid #2a2a4a; border-radius:12px; padding:12px; text-align:center; }
.img-state-card img { max-width:100%; max-height:200px; object-fit:contain; border-radius:8px; }
.img-state-card .label { margin-top:8px; font-size:13px; color:#ccc; }
.img-state-card .version-info { font-size:11px; color:#6366f1; cursor:pointer; margin-top:4px; }
.img-state-card .version-info:hover { text-decoration:underline; }

/* Version list in modal */
.version-item { display:flex; align-items:center; gap:12px; padding:12px; border:1px solid #2a2a4a; border-radius:8px; margin-bottom:8px; background:#0f0f1a; }
.version-item img { width:80px; height:80px; object-fit:contain; border-radius:6px; background:#1a1a2e; }
.version-item .meta { flex:1; }
.version-item .meta .ver-num { font-weight:600; }
.version-item .meta .ver-date { font-size:12px; color:#888; }
.version-item .meta .ver-prompt { font-size:11px; color:#666; margin-top:4px; max-height:40px; overflow:hidden; }
.version-item.current { border-color:#6366f1; }
.version-item .star { cursor:pointer; font-size:18px; }
.version-item .star.active { color:#f59e0b; }

/* Memory timeline */
.memory-timeline { position:relative; padding-left:24px; }
.memory-timeline::before { content:''; position:absolute; left:8px; top:0; bottom:0; width:2px; background:#2a2a4a; }
.memory-group { margin-bottom:24px; }
.memory-group .age-label { font-size:14px; font-weight:600; color:#6366f1; margin-bottom:8px; position:relative; }
.memory-group .age-label::before { content:''; position:absolute; left:-20px; top:6px; width:10px; height:10px; border-radius:50%; background:#6366f1; }
.memory-item { background:#1a1a2e; border:1px solid #2a2a4a; border-radius:8px; padding:12px; margin-bottom:8px; cursor:pointer; }
.memory-item:hover { border-color:#6366f1; }
.memory-item .mem-title { font-size:13px; font-weight:500; }
.memory-item .mem-meta { font-size:11px; color:#888; margin-top:4px; display:flex; gap:8px; }
.memory-item .mem-type { padding:1px 6px; border-radius:4px; font-size:10px; }
.memory-item .mem-type.vivid { background:#6366f120; color:#6366f1; }
.memory-item .mem-type.fragment { background:#f59e0b20; color:#f59e0b; }
.memory-item .mem-type.feeling { background:#22c55e20; color:#22c55e; }
.memory-item .mem-content { font-size:13px; color:#aaa; line-height:1.6; margin-top:8px; display:none; }
.memory-item.expanded .mem-content { display:block; }
.importance-bar { width:60px; height:4px; background:#2a2a4a; border-radius:2px; display:inline-block; vertical-align:middle; }
.importance-bar .fill { height:100%; border-radius:2px; background:#6366f1; }
```

- [ ] **Step 3: Replace the JavaScript**

Replace the entire `<script>` block with the new JS that handles navigation, detail views, version management, memories, and creation modes:

```javascript
const API = "http://127.0.0.1:18900/api/admin";
const STATES = ["idle","thinking","speaking","listening","happy","sad","surprised"];
const STATE_LABELS = {idle:"待机",thinking:"思考",speaking:"说话",listening:"倾听",happy:"开心",sad:"难过",surprised:"惊讶"};
let characters = [];
let currentCharId = null;

async function fetchJSON(url, opts) {
  const res = await fetch(url, opts);
  return res.json();
}

// ---- Navigation ----
function showList() {
  document.getElementById('page-list').style.display = '';
  document.getElementById('page-detail').style.display = 'none';
  document.getElementById('createBtn').style.display = '';
  document.getElementById('pageTitle').textContent = 'Nomi 角色管理后台';
  currentCharId = null;
  loadCharacters();
}

function showDetail(charId) {
  currentCharId = charId;
  const c = characters.find(x => x.id === charId);
  document.getElementById('page-list').style.display = 'none';
  document.getElementById('page-detail').style.display = '';
  document.getElementById('createBtn').style.display = 'none';
  document.getElementById('detailName').textContent = c.name;
  document.getElementById('pageTitle').textContent = c.name;
  switchDetailTab('info');
  loadDetailInfo(c);
  loadDetailImages(c);
  loadDetailVoice(c);
  loadDetailMemories(charId);
}

function switchDetailTab(tab) {
  document.querySelectorAll('#detailTabs .tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.detail-panel').forEach(p => p.classList.remove('active'));
  event.target.classList.add('active');
  document.getElementById('detail-' + tab).classList.add('active');
}

// ---- Character List ----
async function loadCharacters() {
  characters = await fetchJSON(API + '/characters');
  const grid = document.getElementById('charGrid');
  grid.innerHTML = characters.map(c => `
    <div class="char-card" onclick="showDetail('${c.id}')" style="cursor:pointer;">
      <div class="char-card-header">
        <img src="${API}/characters/${c.id}/image/idle" onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 48 48%22><rect fill=%22%232a2a4a%22 width=%2248%22 height=%2248%22/><text x=%2224%22 y=%2230%22 fill=%22%23888%22 text-anchor=%22middle%22 font-size=%2220%22>${c.name[0]}</text></svg>'">
        <div>
          <h3>${c.name}</h3>
          <div class="status">${c.has_voice ? '🔊 有语音' : '🔇 无语音'} · ${Object.values(c.states).filter(Boolean).length}/${STATES.length} 表情</div>
        </div>
      </div>
      <div class="char-card-body">
        <div class="states-grid">
          ${STATES.map(s => c.states[s]
            ? `<div class="state-thumb"><img src="${API}/characters/${c.id}/image/${s}"><div class="label">${STATE_LABELS[s]}</div></div>`
            : `<div class="state-thumb missing"></div>`
          ).join('')}
        </div>
      </div>
    </div>
  `).join('');
}

// ---- Detail: Info ----
function loadDetailInfo(c) {
  document.getElementById('detail-info').innerHTML = `
    <div class="info-grid">
      <div class="info-block">
        <label>性格</label>
        <div class="value">${JSON.stringify(c.personality, null, 2) || '(未设置)'}</div>
      </div>
      <div class="info-block">
        <label>说话风格</label>
        <div class="value">${JSON.stringify(c.speaking_style, null, 2) || '(未设置)'}</div>
      </div>
      <div class="info-block" style="grid-column:1/-1;">
        <label>背景故事</label>
        <div class="value">${c.origin_story || '(未设置)'}</div>
      </div>
      <div class="info-block" style="grid-column:1/-1;">
        <label>系统提示词</label>
        <div class="prompt-box">${c.system_prompt || '(未设置)'}</div>
      </div>
    </div>
  `;
}

// ---- Detail: Images ----
function loadDetailImages(c) {
  const html = `
    <div style="display:grid; grid-template-columns:repeat(auto-fill,minmax(180px,1fr)); gap:16px;">
      ${STATES.map(s => `
        <div class="img-state-card">
          ${c.states[s]
            ? `<img src="${API}/characters/${c.id}/image/${s}?t=${Date.now()}">`
            : `<div style="height:150px; display:flex; align-items:center; justify-content:center; color:#444; font-size:40px;">?</div>`
          }
          <div class="label">${STATE_LABELS[s]}</div>
          <div class="version-info" onclick="showVersionHistory('${c.id}', '${s}')">版本历史</div>
        </div>
      `).join('')}
    </div>
    <div class="btn-group" style="margin-top:20px;">
      <button class="btn btn-primary" onclick="openGeneratePanel('${c.id}')">生成图片</button>
      <button class="btn btn-secondary" onclick="removeBgForChar('${c.id}')">去除背景</button>
    </div>
    <div id="genSection" style="display:none; margin-top:20px;">
      <div class="form-group">
        <label>上传参考图（可选）</label>
        <input type="file" id="refImageInput" accept="image/*">
      </div>
      <div class="form-group">
        <label>基础描述 (Base Prompt)</label>
        <textarea id="genBasePrompt" style="min-height:100px;">${c.prompts?.base_prompt || ''}</textarea>
      </div>
      <h3 style="margin:12px 0 8px; font-size:13px; color:#888;">各状态描述</h3>
      ${STATES.map(s => `
        <div class="form-group">
          <label>${STATE_LABELS[s]}</label>
          <input id="statePrompt_${s}" value="${c.prompts?.states?.[s]?.prompt || ''}">
        </div>
      `).join('')}
      <button class="btn btn-primary" onclick="generateImages('${c.id}')">开始生成</button>
      <div class="log" id="genLog" style="display:none;"></div>
    </div>
  `;
  document.getElementById('detail-images').innerHTML = html;
}

function openGeneratePanel(charId) {
  document.getElementById('genSection').style.display = '';
}

async function generateImages(charId) {
  const basePrompt = document.getElementById('genBasePrompt').value;
  const statePrompts = {};
  STATES.forEach(s => {
    const val = document.getElementById('statePrompt_' + s).value;
    if (val) statePrompts[s] = val;
  });
  if (!basePrompt) { alert('请填写基础描述'); return; }

  // Upload reference image if provided
  const refFile = document.getElementById('refImageInput')?.files?.[0];
  if (refFile) {
    const refForm = new FormData();
    refForm.append('image', refFile);
    await fetch(API + '/characters/' + charId + '/upload-reference', { method: 'POST', body: refForm });
  }

  const log = document.getElementById('genLog');
  log.style.display = 'block';
  log.textContent = '开始生成...\n';

  const form = new FormData();
  form.append('base_prompt', basePrompt);
  form.append('state_prompts', JSON.stringify(statePrompts));

  try {
    const res = await fetchJSON(API + '/characters/' + charId + '/generate-images', { method: 'POST', body: form });
    for (const [s, r] of Object.entries(res.results)) {
      log.textContent += `${STATE_LABELS[s]}: ${r.ok ? '✓' : '✗ ' + r.error}\n`;
    }
    log.textContent += '生成完成！\n';
    // Reload images
    const c = characters.find(x => x.id === charId);
    if (c) {
      // Refresh states
      c.states = {};
      STATES.forEach(s => { if (res.results[s]?.ok) c.states[s] = true; });
    }
    loadDetailImages(characters.find(x => x.id === charId));
  } catch (e) {
    log.textContent += '错误: ' + e.message + '\n';
  }
}

async function removeBgForChar(charId) {
  try {
    const res = await fetchJSON(API + '/characters/' + charId + '/remove-bg', { method: 'POST' });
    alert('已处理: ' + res.processed.join(', '));
    loadDetailImages(characters.find(x => x.id === charId));
  } catch (e) {
    alert('失败: ' + e.message);
  }
}

// ---- Version History ----
async function showVersionHistory(charId, state) {
  document.getElementById('versionModalTitle').textContent = `${STATE_LABELS[state]} - 版本历史`;
  const versions = await fetchJSON(API + '/characters/' + charId + '/versions?asset_type=image&asset_key=' + state);

  if (versions.length === 0) {
    document.getElementById('versionModalBody').innerHTML = '<p style="color:#888;">暂无历史版本</p>';
  } else {
    document.getElementById('versionModalBody').innerHTML = versions.map(v => `
      <div class="version-item ${v.is_current ? 'current' : ''}">
        <img src="${v.is_current
          ? API + '/characters/' + charId + '/image/' + state + '?t=' + Date.now()
          : API + '/characters/' + charId + '/versions/' + v.id + '/file'
        }">
        <div class="meta">
          <span class="ver-num">v${v.version_number}</span>
          ${v.is_current ? '<span style="color:#6366f1; font-size:11px; margin-left:6px;">当前使用</span>' : ''}
          <div class="ver-date">${new Date(v.created_at).toLocaleString('zh-CN')}</div>
          ${v.metadata?.prompt ? `<div class="ver-prompt">${v.metadata.prompt.substring(0, 100)}...</div>` : ''}
        </div>
        <span class="star ${v.is_starred ? 'active' : ''}" onclick="toggleStar('${charId}','${v.id}',this)">
          ${v.is_starred ? '★' : '☆'}
        </span>
        ${!v.is_current ? `<button class="btn btn-sm btn-primary" onclick="activateVersion('${charId}','${v.id}','${state}')">使用此版本</button>` : ''}
      </div>
    `).join('');
  }
  document.getElementById('versionModal').classList.add('show');
}

function closeVersionModal() {
  document.getElementById('versionModal').classList.remove('show');
}

async function activateVersion(charId, versionId, state) {
  await fetchJSON(API + '/characters/' + charId + '/versions/' + versionId + '/activate', { method: 'POST' });
  closeVersionModal();
  // Reload character data and images
  characters = await fetchJSON(API + '/characters');
  loadDetailImages(characters.find(x => x.id === charId));
}

async function toggleStar(charId, versionId, el) {
  const res = await fetchJSON(API + '/characters/' + charId + '/versions/' + versionId + '/star', { method: 'POST' });
  el.textContent = res.is_starred ? '★' : '☆';
  el.classList.toggle('active', res.is_starred);
}

// ---- Detail: Voice ----
function loadDetailVoice(c) {
  const vp = c.voice_profile || {};
  document.getElementById('detail-voice').innerHTML = `
    <div class="info-block">
      <label>语音配置</label>
      <div class="value" style="font-family:monospace; font-size:12px;">${JSON.stringify(vp, null, 2)}</div>
    </div>
    ${c.has_voice ? `
      <div class="voice-section" style="margin-top:12px;">
        <label>试听</label>
        <audio controls src="http://127.0.0.1:18900/api/tts/speak?text=你好，我是${encodeURIComponent(c.name)}&robot_name=${encodeURIComponent(c.name)}"></audio>
      </div>
    ` : '<p style="color:#888; margin-top:12px;">暂无语音配置</p>'}
  `;
}

// ---- Detail: Memories ----
async function loadDetailMemories(charId) {
  const memories = await fetchJSON(API + '/characters/' + charId + '/memories');
  if (memories.length === 0) {
    document.getElementById('detail-memories').innerHTML = '<p style="color:#888;">暂无记忆</p>';
    return;
  }

  // Group by age
  const groups = {};
  for (const m of memories) {
    const age = m.age ?? 0;
    if (!groups[age]) groups[age] = [];
    groups[age].push(m);
  }

  let html = '<div class="memory-timeline">';
  for (const age of Object.keys(groups).sort((a, b) => a - b)) {
    html += `<div class="memory-group">
      <div class="age-label">${age} 岁</div>`;
    for (const m of groups[age]) {
      const opacity = Math.max(0.3, m.strength || 0.5);
      html += `
        <div class="memory-item" onclick="this.classList.toggle('expanded')" style="opacity:${opacity}">
          <div class="mem-title">${m.title || '(无标题)'}</div>
          <div class="mem-meta">
            <span class="mem-type ${m.memory_type || ''}">${m.memory_type || ''}</span>
            <span class="importance-bar"><span class="fill" style="width:${(m.importance || 0.5) * 100}%"></span></span>
            ${m.symbolic_tags?.length ? m.symbolic_tags.map(t => `<span style="font-size:10px; color:#6366f1;">#${t}</span>`).join(' ') : ''}
          </div>
          <div class="mem-content">${m.content || ''}</div>
        </div>`;
    }
    html += '</div>';
  }
  html += '</div>';
  document.getElementById('detail-memories').innerHTML = html;
}

// ---- Create Character ----
function showCreateModal() {
  document.getElementById('createModal').classList.add('show');
}
function closeCreateModal() {
  document.getElementById('createModal').classList.remove('show');
}

function switchCreateMode(mode) {
  document.querySelectorAll('#createModal .tabs .tab').forEach(t => t.classList.remove('active'));
  event.target.classList.add('active');
  document.getElementById('create-manual').style.display = mode === 'manual' ? '' : 'none';
  document.getElementById('create-web').style.display = mode === 'web' ? '' : 'none';
}

async function createCharacter() {
  const form = new FormData();
  form.append('name', document.getElementById('newName').value);
  form.append('dir_name', document.getElementById('newDirName').value);
  form.append('origin_story', document.getElementById('newStory').value);
  form.append('personality', document.getElementById('newPersonality').value || '{}');
  form.append('system_prompt', document.getElementById('newPrompt').value);

  const el = document.getElementById('createResult');
  el.innerHTML = '<span class="loading">创建中...</span>';
  try {
    const res = await fetchJSON(API + '/characters/create', { method: 'POST', body: form });
    if (res.error) { el.innerHTML = `<span class="error">${res.error}</span>`; return; }
    el.innerHTML = `<span class="success">创建成功！</span>`;
    closeCreateModal();
    loadCharacters();
  } catch (e) { el.innerHTML = `<span class="error">失败: ${e.message}</span>`; }
}

async function createFromWeb() {
  const name = document.getElementById('webCharName').value;
  const source = document.getElementById('webSource').value;
  if (!name || !source) { alert('请填写角色名称和来源作品'); return; }

  const log = document.getElementById('webCreateLog');
  log.style.display = 'block';
  log.textContent = '开始创建...\n';

  try {
    const res = await fetch(API + '/characters/create-from-web', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ character_name: name, source: source }),
    });
    const data = await res.json();
    const jobId = data.job_id;

    // Poll status
    const poll = setInterval(async () => {
      const status = await fetchJSON(API + '/characters/create-from-web/status/' + jobId);
      log.textContent = `状态: ${status.status}\n${status.progress}\n`;
      if (status.status === 'completed' || status.status === 'failed') {
        clearInterval(poll);
        if (status.status === 'completed') {
          log.textContent += '\n创建完成！';
          closeCreateModal();
          loadCharacters();
          if (status.robot_id) {
            // Wait for characters to load, then show detail
            setTimeout(() => {
              const c = characters.find(x => x.id === status.robot_id);
              if (c) showDetail(status.robot_id);
            }, 1000);
          }
        }
      }
    }, 2000);
  } catch (e) {
    log.textContent += '错误: ' + e.message + '\n';
  }
}

// ---- Init ----
document.addEventListener('DOMContentLoaded', loadCharacters);
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    closeCreateModal();
    closeVersionModal();
  }
});
```

- [ ] **Step 4: Verify the page loads**

Open the admin panel in a browser at `http://127.0.0.1:18900/api/admin/panel` (or wherever it's served) and verify:
- Character list renders with cards
- Clicking a card shows the detail page with 4 tabs
- Back button returns to list
- Create modal opens with two modes
- Version history modal opens (may show empty initially)

- [ ] **Step 5: Commit**

```bash
git add backend/app/admin_panel.html
git commit -m "feat(admin): rewrite admin panel with detail page, versions, memories, web creation"
```

---

### Task 5: Integration and Smoke Test

**Files:**
- No new files

- [ ] **Step 1: Start the backend and verify all endpoints**

```bash
cd /Users/chao/Documents/Projects/nomi/backend && python -m uvicorn app.main:app --reload --port 18900
```

Test these endpoints manually or via curl:

```bash
# List characters
curl http://127.0.0.1:18900/api/admin/characters

# Get memories for a character (replace {id} with actual UUID)
curl http://127.0.0.1:18900/api/admin/characters/{id}/memories

# Get versions (should be empty initially)
curl "http://127.0.0.1:18900/api/admin/characters/{id}/versions?asset_type=image&asset_key=idle"
```

- [ ] **Step 2: Test the full flow in the browser**

1. Open admin panel
2. Click a character card → verify detail page shows info, images, memories
3. Click "版本历史" on an image → verify modal appears
4. Click "创建角色" → switch to "从网络构建" tab
5. Enter a character name and source → click "开始构建"
6. Watch the progress log until completion

- [ ] **Step 3: Verify existing image generation still works with versioning**

1. Go to a character detail → Images tab
2. Click "生成图片" → fill in prompts → generate
3. After generation, check "版本历史" → should show the old and new versions
4. Click "使用此版本" on an older version → verify the image switches back

- [ ] **Step 4: Commit any fixes**

```bash
git add -A
git commit -m "fix(admin): integration fixes for admin panel upgrade"
```
