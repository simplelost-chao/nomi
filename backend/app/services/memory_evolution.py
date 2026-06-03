"""Memory evolution — decay, activation, reconsolidation, and personality refresh."""

import json
import math
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Memory, Robot

DEFAULT_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


async def decay_memories(session: AsyncSession) -> None:
    """Apply time-based decay to all memories. Called periodically.

    hours_since = hours since last_activated
    time_decay = e^(-0.01 * hours_since)
    new_strength = max(base_importance * 0.3, time_decay)
    """
    now = datetime.utcnow()
    result = await session.execute(select(Memory))
    memories = list(result.scalars().all())

    for memory in memories:
        base = memory.base_importance if memory.base_importance is not None else 0.5
        last = memory.last_activated or memory.created_at
        # Ensure naive datetime for comparison

        hours_since = (now - last).total_seconds() / 3600.0
        time_decay = math.exp(-0.01 * hours_since)
        new_strength = max(base * 0.3, time_decay)
        memory.importance_score = new_strength

    await session.commit()


async def activate_memories(session: AsyncSession, memory_ids: list[uuid.UUID]) -> None:
    """Boost memories when they are recalled.

    - Updates last_activated and activation_count
    - Boosts importance_score = min(1.0, base_importance + 0.2)
    - Slightly boosts linked memories (+0.05)
    """
    if not memory_ids:
        return

    now = datetime.utcnow()
    result = await session.execute(
        select(Memory).where(Memory.id.in_(memory_ids))
    )
    memories = list(result.scalars().all())

    linked_ids: set[uuid.UUID] = set()
    for memory in memories:
        memory.last_activated = now
        memory.activation_count = (memory.activation_count or 0) + 1
        base = memory.base_importance if memory.base_importance is not None else 0.5
        memory.importance_score = min(1.0, base + 0.2)
        if memory.linked_memory_ids:
            linked_ids.update(memory.linked_memory_ids)

    # Remove already-activated ids so we don't double-boost
    linked_ids -= set(memory_ids)

    if linked_ids:
        linked_result = await session.execute(
            select(Memory).where(Memory.id.in_(linked_ids))
        )
        for linked in linked_result.scalars().all():
            current = linked.importance_score or 0.0
            linked.importance_score = min(1.0, current + 0.05)

    await session.commit()


# --- Prompts ---

_SUMMARIZE_PROMPT = """你是记忆整理助手。请将以下对话总结为一段记忆，并用 JSON 输出：

对话（{robot_name} 与用户）：
{conversation_text}

请输出：
{{
  "summary": "简洁的记忆摘要（1-3句，第三人称，描述发生了什么）",
  "importance": 0.0到1.0的浮点数（0=完全不重要，1=极其重要，日常闲聊约0.3，情感交流约0.6，重大事件约0.9）,
  "emotional_tags": ["情绪标签列表，如：快乐、好奇、感动"],
  "related_topics": ["相关话题关键词"]
}}

只输出 JSON。"""

_RECONSOLIDATE_PROMPT = """你是记忆整理助手。一个小生命有了新体验，请判断它是否改变了对某段旧记忆的理解。

新记忆摘要：
{new_summary}

旧记忆列表（每条有id和内容）：
{old_memories_text}

如果新记忆对某条旧记忆有新的诠释或理解，请输出：
{{
  "recontextualized": true,
  "memory_id": "旧记忆的UUID",
  "reinterpretation": "新的理解或感悟（1-2句话）"
}}

如果没有任何旧记忆被重新诠释，输出：
{{
  "recontextualized": false
}}

只输出 JSON。"""

_PORTRAIT_PROMPT = """你是性格演化师。根据这个小生命的所有记忆，重新描绘它的性格与内心状态。

小生命：{robot_name}
上一次的性格描述：{previous_portrait}

近期有效记忆（强度 > 0.2）：
{memories_text}

请输出更新后的性格（保持渐进演化，不要剧烈改变）：
{{
  "personality": ["性格特征列表，每项是一个简短描述"],
  "portrait_summary": "一段话描述当前的内心状态和成长变化",
  "emotional_baseline": "平静/好奇/温暖/忧郁/活泼/等基础情绪基调"
}}

只输出 JSON。"""


async def save_conversation_memory(
    session: AsyncSession,
    llm,
    robot: Robot,
    conversation_messages: list[dict],
) -> Memory | None:
    """Summarize a conversation and save it as a memory.

    Also checks if this new memory reconsolidates any existing memory.
    Returns the new Memory object, or None if nothing worth saving.
    """
    if not conversation_messages:
        return None

    # Build conversation text
    convo_text = "\n".join(
        f"{m.get('sender', '?')}: {m.get('content', '')}"
        for m in conversation_messages
    )

    # Step 1: Summarize the conversation
    prompt = _SUMMARIZE_PROMPT.format(
        robot_name=robot.name,
        conversation_text=convo_text,
    )
    try:
        summary_data = await llm.generate_structured(
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        print(f"[memory_evolution] Failed to summarize conversation: {e}")
        return None

    summary = summary_data.get("summary", "")
    importance = float(summary_data.get("importance", 0.3))
    emotional_tags = summary_data.get("emotional_tags", [])

    if not summary:
        return None

    # Step 2: Check for reconsolidation against existing memories
    # Fetch recent strong memories for this robot
    existing_result = await session.execute(
        select(Memory)
        .where(
            Memory.owner_id == robot.id,
            Memory.owner_type == "robot",
            Memory.importance_score >= 0.2,
        )
        .order_by(Memory.created_at.desc())
        .limit(20)
    )
    existing_memories = list(existing_result.scalars().all())

    linked_ids: list[uuid.UUID] = []
    reinterpreted_memory_id: uuid.UUID | None = None

    if existing_memories:
        old_memories_text = "\n".join(
            f"- id={m.id} 内容：{m.summary or m.content or ''}"
            for m in existing_memories
        )
        recon_prompt = _RECONSOLIDATE_PROMPT.format(
            new_summary=summary,
            old_memories_text=old_memories_text,
        )
        try:
            recon_data = await llm.generate_structured(
                messages=[{"role": "user", "content": recon_prompt}],
            )
            if recon_data.get("recontextualized"):
                raw_id = recon_data.get("memory_id")
                if raw_id:
                    try:
                        reinterpreted_memory_id = uuid.UUID(str(raw_id))
                    except ValueError:
                        pass

            # Collect related memory ids as links (top 3 by importance)
            top_related = sorted(existing_memories, key=lambda m: m.importance_score or 0, reverse=True)[:3]
            linked_ids = [m.id for m in top_related]
        except Exception as e:
            print(f"[memory_evolution] Reconsolidation check failed: {e}")

    # Step 3: Apply reinterpretation to old memory if found
    if reinterpreted_memory_id:
        recon_mem_result = await session.execute(
            select(Memory).where(Memory.id == reinterpreted_memory_id)
        )
        recon_mem = recon_mem_result.scalar_one_or_none()
        if recon_mem:
            recon_mem.reinterpretation = recon_data.get("reinterpretation", "")

    # Step 4: Save the new memory (with embedding for semantic retrieval)
    embedding = None
    try:
        embedding = await llm.embed(summary[:500])
    except Exception:
        pass

    now = datetime.utcnow()
    new_memory = Memory(
        user_id=robot.user_id,
        owner_type="robot",
        owner_id=robot.id,
        memory_type="episodic",
        content=convo_text[:2000],
        summary=summary,
        importance_score=importance,
        base_importance=importance,
        emotional_tags=emotional_tags if emotional_tags else None,
        last_activated=now,
        activation_count=0,
        memory_source="conversation",
        linked_memory_ids=linked_ids if linked_ids else None,
        embedding=embedding,
    )
    session.add(new_memory)
    await session.commit()
    await session.refresh(new_memory)
    return new_memory


async def save_thought_memory(
    session: AsyncSession,
    robot: Robot,
    thought: str,
    base_importance: float = 0.2,
    llm=None,
) -> Memory:
    """Save a heartbeat thought as a low-importance memory, with optional embedding."""
    now = datetime.utcnow()

    # Generate embedding for semantic retrieval
    embedding = None
    if llm:
        try:
            embedding = await llm.embed(thought[:500])
        except Exception:
            pass

    memory = Memory(
        user_id=robot.user_id,
        owner_type="robot",
        owner_id=robot.id,
        memory_type="thought",
        content=thought,
        summary=thought[:200],
        importance_score=base_importance,
        base_importance=base_importance,
        last_activated=now,
        activation_count=0,
        memory_source="thought",
        embedding=embedding,
    )
    session.add(memory)
    await session.commit()
    await session.refresh(memory)
    return memory


async def check_evolution(session: AsyncSession, llm, robot: Robot) -> bool:
    """Check if the robot's personality should evolve based on new memories.

    Triggers portrait refresh if:
    - >= 10 new memories since last portrait update, OR
    - any memory has been reinterpreted

    Returns True if evolution happened.
    """
    # Find memories newer than last portrait update
    # We use robot.updated_at as a proxy for when portrait was last regenerated
    portrait_last_updated = robot.updated_at or robot.created_at

    new_memories_result = await session.execute(
        select(Memory)
        .where(
            Memory.owner_id == robot.id,
            Memory.owner_type == "robot",
            Memory.created_at > portrait_last_updated,
        )
    )
    new_memories = list(new_memories_result.scalars().all())

    # Check for reinterpreted memories
    has_reinterpreted = any(m.reinterpretation for m in new_memories)

    should_evolve = len(new_memories) >= 10 or has_reinterpreted
    if not should_evolve:
        return False

    # Fetch all strong memories for portrait regeneration
    strong_memories_result = await session.execute(
        select(Memory)
        .where(
            Memory.owner_id == robot.id,
            Memory.owner_type == "robot",
            Memory.importance_score >= 0.2,
        )
        .order_by(Memory.importance_score.desc())
        .limit(50)
    )
    strong_memories = list(strong_memories_result.scalars().all())

    memories_text = "\n".join(
        f"- [{m.memory_source or 'memory'}] {m.summary or m.content or ''}"
        + (f" (重新诠释：{m.reinterpretation})" if m.reinterpretation else "")
        for m in strong_memories
    )

    previous_portrait = json.dumps(robot.portrait or {}, ensure_ascii=False)

    portrait_prompt = _PORTRAIT_PROMPT.format(
        robot_name=robot.name,
        previous_portrait=previous_portrait,
        memories_text=memories_text or "（暂无记忆）",
    )

    try:
        portrait_data = await llm.generate_structured(
            messages=[{"role": "user", "content": portrait_prompt}],
        )
    except Exception as e:
        print(f"[memory_evolution] Portrait evolution failed: {e}")
        return False

    # Update robot — gradual evolution
    new_personality = portrait_data.get("personality")
    if new_personality and isinstance(new_personality, list):
        robot.personality = new_personality

    # Merge into portrait
    current_portrait = dict(robot.portrait or {})
    current_portrait["summary"] = portrait_data.get("portrait_summary", "")
    current_portrait["emotional_baseline"] = portrait_data.get("emotional_baseline", "")
    current_portrait["last_evolved"] = datetime.utcnow().isoformat()
    robot.portrait = current_portrait

    await session.commit()
    print(f"[memory_evolution] {robot.name}'s personality evolved based on {len(new_memories)} new memories.")
    return True
