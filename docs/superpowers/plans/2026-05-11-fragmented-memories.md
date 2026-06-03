# Fragmented Memories Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace 9 long memories with ~80 short memory fragments generated in batches with ongoing_state for continuity.

**Architecture:** New `build_batch_memories_prompt` replaces the old two-step (moments selection + per-moment expansion). Memories are generated in time-period batches, each batch receiving the previous batch's `ongoing_state` to maintain physical/emotional/relational continuity. DB schema gets one new column (`batch_index`).

**Tech Stack:** Python, SQLAlchemy, Alembic, Claude API (via existing LLM abstraction)

---

### Task 1: Add `batch_index` column to YearlyMemory

**Files:**
- Modify: `backend/app/db/models.py:70-90`
- Create: `backend/alembic/versions/<auto>_add_batch_index_to_yearly_memories.py`

- [ ] **Step 1: Add column to model**

In `backend/app/db/models.py`, add `batch_index` to `YearlyMemory` class, after the `generation_cost_usd` line (line 87):

```python
    generation_cost_usd: Mapped[float | None] = mapped_column(Float, default=0.0)
    batch_index: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)
```

- [ ] **Step 2: Generate alembic migration**

```bash
cd /Users/chao/projects/nomi/backend && python -m alembic revision --autogenerate -m "add batch_index to yearly_memories"
```

Expected: Creates a new migration file in `backend/alembic/versions/`.

- [ ] **Step 3: Run the migration**

```bash
cd /Users/chao/projects/nomi/backend && python -m alembic upgrade head
```

Expected: `INFO  [alembic.runtime.migration] Running upgrade ... -> ..., add batch_index to yearly_memories`

- [ ] **Step 4: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/*batch_index*
git commit -m "feat: add batch_index column to yearly_memories"
```

---

### Task 2: Write `build_batch_memories_prompt`

**Files:**
- Modify: `backend/app/prompts/creation.py`

This is the core prompt change. Replace the old two-step prompts with a single batch prompt.

- [ ] **Step 1: Replace `build_life_moments_prompt` and `build_moment_detail_prompt` with `build_batch_memories_prompt`**

In `backend/app/prompts/creation.py`, delete `build_life_moments_prompt` (lines 96-150) and `build_moment_detail_prompt` (lines 153-208) and `build_moment_summary_prompt` (lines 211-213). Replace with:

```python
def _compute_batches(robot_age: int) -> list[tuple[int, int]]:
    """Split a life into time-period batches. Returns list of (start_age, end_age)."""
    if robot_age <= 3:
        splits = [0, robot_age]
    elif robot_age <= 8:
        splits = [0, 2, 5, robot_age]
    elif robot_age <= 15:
        splits = [0, 2, 5, 10, robot_age]
    elif robot_age <= 30:
        splits = [0, 2, 5, 10, 20, robot_age]
    else:
        splits = [0, 3, 8, 15, 25, 40, robot_age]

    # Remove splits beyond robot_age and deduplicate
    splits = sorted(set(s for s in splits if s <= robot_age))
    if splits[-1] != robot_age:
        splits.append(robot_age)

    return [(splits[i], splits[i + 1]) for i in range(len(splits) - 1)]


def _compute_target_count(robot_age: int) -> int:
    """Total memories to generate, scaled by age."""
    return max(20, min(120, robot_age * 8))


def build_batch_memories_prompt(
    robot_name: str,
    robot_age: int,
    object_description: str,
    personality: list[str],
    core_desire: str,
    core_fear: str,
    birth_place: str,
    batch_start_age: int,
    batch_end_age: int,
    target_count: int,
    batch_index: int,
    total_batches: int,
    ongoing_state: dict | None = None,
    previous_memories_tail: list[dict] | None = None,
    life_theme: str = "",
) -> tuple[str, str]:
    """Generate a batch of short memory fragments for one time period."""

    is_first_batch = batch_index == 0

    ongoing_block = ""
    if ongoing_state:
        import json as _json
        ongoing_block = f"""
当前累积状态（你必须在新记忆中保持这些状态的一致性）：
{_json.dumps(ongoing_state, ensure_ascii=False, indent=2)}

规则：
- physical 中的状态只增不减（裂痕不会自己消失，除非有修复事件并在记忆中描述）
- 如果状态发生变化（搬家、换主人、被修复），必须有一条记忆描述这个变化
- 不要凭空出现或消失任何状态"""

    prev_block = ""
    if previous_memories_tail:
        prev_lines = "\n".join(
            f"- 【{m.get('time', '')}】{m.get('content', '')[:100]}"
            for m in previous_memories_tail
        )
        prev_block = f"\n上一段时间的最后几条记忆（保持衔接）：\n{prev_lines}"

    life_theme_block = ""
    if life_theme:
        life_theme_block = f"\n这一生的主题：{life_theme}"

    first_batch_extra = ""
    if is_first_batch:
        first_batch_extra = """
这是第一批记忆，请同时确定 life_theme（这一生的主题，一句话）。
第一条记忆应该是"出生"——从工厂/手工/窑炉/盒子里来到世界的瞬间。"""

    system = f"""你是 {robot_name}，一个有生命的物品。你正在回忆自己生命中的碎片。

你是：{object_description}
年龄：{robot_age}年
出生地：{birth_place}
性格：{personality}
愿望：{core_desire}
恐惧：{core_fear}
{life_theme_block}

你现在要回忆 {batch_start_age} 到 {batch_end_age} 岁之间的事（第 {batch_index + 1}/{total_batches} 段）。
请生成约 {target_count} 条短记忆。

## 什么是短记忆

每条 80-250 字。不是散文，不是叙事，是记忆碎片：
- 一个画面："她把我从地上捡起来，手指在裂口上摸了一下"
- 一种感觉："那段时间柜子里很暗，灰尘慢慢落在我身上"
- 一句话："有一天她对我说'你怎么还在这'"
- 一个瞬间："被装进盒子的时候，我听到胶带撕开的声音"

不要写成一段完整的故事。每条记忆是独立的碎片，但碎片之间有时间顺序和因果关系。

## 感知规则

- 你的感知方式由材质和形态决定——陶瓷杯感受液体温度和嘴唇触碰，毛绒玩偶感受拥抱力度和体温，高达模型感受关节转动
- 每个物品的"出生"完全不同——工厂流水线、手工缝制、窑炉烧制、从盒子里被拿出来
- 不要用"光"作为开头或核心意象，除非你真的是灯或跟光有关的物品
- 每条记忆的第一句话要独特，避免千篇一律

## 密度变化

- 被频繁使用的时期 → 记忆密集（可以多几条）
- 被遗忘在角落的岁月 → 只有 1-2 条模糊感受
- 在目标数量 {target_count} 附近自由分配，不需要精确
{ongoing_block}
{prev_block}
{first_batch_extra}"""

    life_theme_field = ""
    if is_first_batch:
        life_theme_field = '\n  "life_theme": "这一生的主题（一句话）",'

    user_msg = f"""请回忆 {batch_start_age}-{batch_end_age} 岁的记忆碎片，用 JSON 格式：
{{
{life_theme_field}
  "memories": [
    {{
      "time": "时间描述（不要精确到年，用'刚来的时候'、'大约三四岁'、'那个冬天'这样的说法）",
      "approximate_age": 大约年龄数字,
      "title": "一句话标题",
      "emotional_core": "核心情感",
      "content": "80-250字的记忆碎片正文（第一人称'我'）",
      "memory_type": "vivid/fragment/feeling",
      "importance": 0.0-1.0
    }}
  ],
  "ongoing_state": {{
    "physical": ["当前的物理状态，如裂痕、磨损、颜色变化"],
    "emotional": ["当前的情感基调"],
    "relationships": ["当前的关系状态"],
    "environment": ["当前所处的环境"]
  }}
}}

memory_type 说明（只影响语气，不影响长度，都是 80-250 字）：
- vivid：清晰的画面，有细节
- fragment：只是一个瞬间
- feeling：一段时期的感受

直接输出 JSON。"""

    return system, user_msg
```

- [ ] **Step 2: Update `build_portrait_prompt` to use `content` instead of `summary`**

In `backend/app/prompts/creation.py`, in `build_portrait_prompt` (around line 232 in the updated file), change:

```python
        memories_text += f"\n【{m['time']}】（记忆清晰度 {strength_pct}%）{m['summary']}"
```

to:

```python
        memories_text += f"\n【{m['time']}】（记忆清晰度 {strength_pct}%）{m['content']}"
```

And update the function signature docstring and the `all_memories_with_strength` expected dict keys — each item now has `content` instead of `summary`.

- [ ] **Step 3: Keep legacy stubs but update imports**

The existing `build_life_moments_prompt`, `build_moment_detail_prompt`, `build_moment_summary_prompt` are imported in other files. Keep the legacy stubs at the bottom of the file (they already exist for `build_yearly_memories_prompt` and `build_life_memories_prompt`):

```python
# Legacy compatibility
def build_robot_creation_prompt(existing_robots, preferences=None):
    return build_robot_creation_from_image_prompt(preferences or "", existing_robots)

def build_yearly_memories_prompt(robot_name, robot_age, origin_story, personality):
    return ("", "")

def build_life_memories_prompt(robot_name, robot_age, origin_story, personality, object_description):
    return ("", "")

def build_life_moments_prompt(**kwargs):
    return ("", "")

def build_moment_detail_prompt(**kwargs):
    return ("", "")

def build_moment_summary_prompt(text):
    return ("", "")
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/prompts/creation.py
git commit -m "feat: add build_batch_memories_prompt, replace two-step generation"
```

---

### Task 3: Rewrite memory generation in `_run_creation`

**Files:**
- Modify: `backend/app/api/robots.py:219-318`

Replace steps 3+4 (life moments + expand each moment) with batched generation.

- [ ] **Step 1: Add import for new prompt function**

In `backend/app/api/robots.py`, replace the imports (lines 14-20):

```python
from app.prompts.creation import (
    build_batch_memories_prompt,
    build_portrait_prompt,
    build_robot_creation_from_image_prompt,
)
from app.prompts.creation import _compute_batches, _compute_target_count
```

- [ ] **Step 2: Update the creation steps list**

In `_run_creation`, update the `steps` list in the job (lines 64-71) — merge "moments" and "memories" into one step:

```python
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
```

- [ ] **Step 3: Replace steps 3+4 with batched generation**

Replace lines 219-318 (the old `=== 3. Life moments ===` and `=== 4. Expand each moment ===` sections) with:

```python
            # === 3. Generate memory fragments in batches ===
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

                batch_result = await llm.generate_structured(
                    messages=[{"role": "user", "content": usr_msg}],
                    system_prompt=sys_msg,
                )
                batch_stats = _get_llm_stats()
                _track()
                memories_cost += batch_stats["cost_usd"]

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
                        generation_time_ms=batch_stats["duration_ms"],
                        generation_cost_usd=round(batch_stats["cost_usd"] / max(1, len(batch_memories)), 4),
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

                await session.commit()

                # Set origin_story from first memory
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
```

- [ ] **Step 4: Update portrait section to use `content` instead of `summary`**

Replace lines 320-333 (the old portrait memory assembly) with:

```python
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
```

- [ ] **Step 5: Update generation_stats to use `memory_count`**

Replace `len(moments)` references in generation_stats (around old lines 344-349 and 372-379) with `memory_count`:

```python
            robot.generation_stats = {
                "total_cost_usd": round(total_cost, 4),
                "total_time_ms": total_elapsed_ms,
                "total_words": total_words,
                "moment_count": memory_count,
            }
```

And in the final stats block:

```python
            robot.generation_stats = {
                "status": "done",
                "total_cost_usd": round(total_cost, 4),
                "total_time_ms": total_elapsed_ms,
                "total_words": total_words,
                "moment_count": memory_count,
                "steps": job["steps"],
            }
```

- [ ] **Step 6: Verify the creation flow compiles**

```bash
cd /Users/chao/projects/nomi/backend && python -c "from app.api.robots import router; print('OK')"
```

Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/robots.py
git commit -m "feat: rewrite _run_creation to use batched memory generation"
```

---

### Task 4: Rewrite `regenerate_memories` endpoint

**Files:**
- Modify: `backend/app/api/regenerate.py:173-262`

- [ ] **Step 1: Update imports**

Replace imports at top of `backend/app/api/regenerate.py` (lines 12-17):

```python
from app.prompts.creation import (
    build_batch_memories_prompt,
    build_portrait_prompt,
    build_robot_creation_from_image_prompt,
)
from app.prompts.creation import _compute_batches, _compute_target_count
```

- [ ] **Step 2: Rewrite `regenerate_memories` function**

Replace the `regenerate_memories` function (lines 173-262) with:

```python
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

        batch_result = await llm.generate_structured(
            messages=[{"role": "user", "content": usr_msg}],
            system_prompt=sys_msg,
        )

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

        await session.commit()

    return {"moment_count": memory_count, "total_words": total_words, "model": model}
```

- [ ] **Step 3: Verify regenerate compiles**

```bash
cd /Users/chao/projects/nomi/backend && python -c "from app.api.regenerate import router; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/regenerate.py
git commit -m "feat: rewrite regenerate_memories to use batched generation"
```

---

### Task 5: End-to-end test with a real robot creation

**Files:** None (manual testing)

- [ ] **Step 1: Start the backend**

```bash
cd /Users/chao/projects/nomi/backend && python -m uvicorn app.main:app --reload --port 8000
```

- [ ] **Step 2: Create a test robot via the frontend or API**

Navigate to the frontend and create a new robot with an image, or use curl:

```bash
curl -X POST http://localhost:8000/api/robots/from-image \
  -F "text_hint=一个旧的陶瓷杯，有裂纹"
```

Watch the logs for batch generation progress.

- [ ] **Step 3: Verify the generated memories**

```bash
# Get the robot ID from the creation response, then:
curl -s http://localhost:8000/api/robots/<ROBOT_ID> | python -m json.tool | head -100
```

Check:
- Memory count is approximately `age × 8`
- Each `memory_content` is 80-250 characters
- `batch_index` is populated
- Memories show continuity (physical state persists across batches)

- [ ] **Step 4: Test regenerate endpoint**

```bash
curl -X POST "http://localhost:8000/api/robots/<ROBOT_ID>/regenerate/memories?model=claude"
```

Verify new memories replace old ones with same quality.

- [ ] **Step 5: Commit any fixes found during testing**

```bash
git add -u
git commit -m "fix: adjustments from end-to-end testing"
```
