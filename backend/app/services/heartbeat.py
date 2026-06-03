"""Heartbeat system — gives each robot an inner life with spontaneous thoughts and conversations."""

import asyncio
import json
import random
import time
import uuid
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import async_session
from app.db.models import Memory, Robot, Message, Conversation

DEFAULT_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_shared_conversation_id: uuid.UUID | None = None


async def _get_shared_conversation() -> uuid.UUID:
    """Get or create the shared conversation (used by both heartbeat and user chat)."""
    global _shared_conversation_id
    if _shared_conversation_id:
        return _shared_conversation_id
    async with async_session() as session:
        result = await session.execute(
            select(Conversation)
            .where(Conversation.user_id == DEFAULT_USER_ID)
            .order_by(Conversation.created_at.desc())
            .limit(1)
        )
        conv = result.scalar_one_or_none()
        if not conv:
            conv = Conversation(user_id=DEFAULT_USER_ID, conversation_type="shared")
            session.add(conv)
            await session.commit()
            await session.refresh(conv)
        _shared_conversation_id = conv.id
        return conv.id


def set_shared_conversation(conv_id: uuid.UUID):
    """Called when user creates/uses a conversation, so heartbeat writes to the same one."""
    global _shared_conversation_id
    _shared_conversation_id = conv_id


async def _save_heartbeat_message(robot_id: uuid.UUID, robot_name: str, content: str):
    """Save a heartbeat speech message to the shared conversation."""
    try:
        conv_id = await _get_shared_conversation()
        async with async_session() as session:
            msg = Message(
                conversation_id=conv_id,
                sender_type="robot",
                sender_id=robot_id,
                sender_name=robot_name,
                content=content,
                metadata_={"source": "heartbeat"},
            )
            session.add(msg)
            await session.commit()
    except Exception as e:
        print(f"[heartbeat] Failed to save message: {e}")


# Track recent searches to avoid repeating
_recent_searches: list[str] = []

# ── Attention system ──
# Tracks what the group is currently focused on. Decays gradually.
_attention: dict = {
    "topic": None,        # The topic string (e.g. "阿瓦隆")
    "source": None,       # Who raised it ("主人", or a robot name)
    "strength": 0.0,      # 0.0 ~ 1.0, decays per heartbeat
    "context": [],        # Recent conversation lines about this topic
}

# Legacy aliases
_user_topic: dict | None = None
_user_topic_ttl = 0


def inject_user_message(sender_name: str, content: str):
    """Called when user sends a chat message — captures group attention."""
    global _user_topic, _user_topic_ttl
    _recent_messages.append({
        "type": "user_message",
        "robot_name": sender_name,
        "content": content,
    })
    if len(_recent_messages) > 20:
        _recent_messages.pop(0)
    # Legacy
    _user_topic = {"sender": sender_name, "content": content}
    _user_topic_ttl = 20
    # Set attention — full strength
    _attention["topic"] = content
    _attention["source"] = sender_name
    _attention["strength"] = 1.0
    _attention["context"] = [f"主人：{content}"]
    # Save as memory
    asyncio.ensure_future(_save_user_inspiration(content))


async def _save_user_inspiration(content: str):
    """Save the user's message as a shared experience memory for all robots."""
    try:
        from app.services.memory_evolution import save_thought_memory
        async with async_session() as session:
            robots = (await session.execute(
                select(Robot).where(Robot.user_id == DEFAULT_USER_ID)
            )).scalars().all()
            for robot in robots:
                await save_thought_memory(
                    session, robot,
                    f"[主人说的话] {content}",
                    base_importance=0.35,
                )
    except Exception as e:
        print(f"[heartbeat] Failed to save user inspiration: {e}")


# Global state
_alive = False
_heartbeat_tasks: dict[str, asyncio.Task] = {}
_event_listeners: list[Callable] = []  # Callbacks for new events
_recent_messages: list[dict] = []  # Recent messages for trigger context
_busy = False  # True while frontend is playing TTS — heartbeat pauses
_busy_since = 0.0  # timestamp when busy was set
_BUSY_TIMEOUT = 30  # auto-clear after 30s (safety)


def is_alive() -> bool:
    return _alive


def set_busy(busy: bool):
    import time
    global _busy, _busy_since
    _busy = busy
    if busy:
        _busy_since = time.time()


def is_busy() -> bool:
    import time
    if _busy and (time.time() - _busy_since) > _BUSY_TIMEOUT:
        set_busy(False)
    return _busy


def add_listener(callback: Callable):
    _event_listeners.append(callback)


def remove_listener(callback: Callable):
    if callback in _event_listeners:
        _event_listeners.remove(callback)


async def _emit(event: dict):
    """Send event to all listeners."""
    # Track recent messages for trigger context
    if event.get("type") == "message":
        _recent_messages.append(event)
        if len(_recent_messages) > 20:
            _recent_messages.pop(0)

    for listener in _event_listeners:
        try:
            await listener(event)
        except Exception:
            pass


HEARTBEAT_INTERVAL = 5  # seconds — the pulse of life (default, can be changed via API)


def set_heartbeat_interval(seconds: int):
    global HEARTBEAT_INTERVAL
    HEARTBEAT_INTERVAL = max(1, min(60, seconds))


def get_heartbeat_interval() -> int:
    return HEARTBEAT_INTERVAL
DECAY_INTERVAL = 300  # seconds — run memory decay every 5 minutes


def _get_inner_drives(robot: Robot) -> dict:
    """Extract inner_drives from robot's current_status JSON."""
    try:
        if robot.current_status and robot.current_status.startswith("{"):
            data = json.loads(robot.current_status)
            return data.get("inner_drives", {})
    except Exception:
        pass
    return {}


CONVERSATION_PROMPT = """你是 {name}，性格：{personality}。

── 对话记录 ──
{conversation_log}

你正在和大家聊天。请直接回应上面的对话。

规则：
1. 回应最后几条消息的内容，不要跑题
2. 深入聊——不要只说"好棒"就完了，要追问细节、分享观点、讨论为什么
3. 如果不知道别人说的东西，直接问具体问题（"这游戏怎么玩？""几个人能玩？""你最喜欢哪个角色？"）
4. 如果有人搜到了新知识，讨论那个知识——提出你的看法、追问更多、联系到之前聊的内容
5. 如果别人纠正了你，接受纠正并继续聊
6. 说人话，口语化，像微信群聊，2-5 句
7. 可以追问、补充、反驳、开玩笑、表达好奇
8. 如果真的没什么要说的，可以不说

禁止：
- 不要写散文、诗歌、抒情长句
- 不要用比喻（不要"像窑里的火"、"像针脚"、"像叶子"）
- 不要编造你没有过的经历
- 不要扯回自己的外表/材质特征，除非跟话题直接相关

你刚才说过的（别重复）：
{recent_thoughts}

只输出 JSON：
{{
  "thought": "一句话内心反应",
  "action": "speak",
  "target": "",
  "say": "你的回复（1-3句，口语化）",
  "reflection": ""
}}
不想说话就 action 写 none，say 写空。只输出 JSON。"""


def _thought_probability(robot: Robot) -> float:
    """Chance of generating a thought on each heartbeat. Driven by inner drives."""
    drives = _get_inner_drives(robot)
    # Base probability from curiosity + sociability + introspection
    curiosity = drives.get("curiosity", 0.5)
    sociability = drives.get("sociability", 0.5)
    introspection = drives.get("introspection", 0.5)
    # Weighted average — more curious/social robots think more
    prob = 0.08 + 0.20 * max(curiosity, sociability, introspection)
    return min(0.40, prob)


THOUGHT_PROMPT = """你是 {name}，一个有生命的物品。
性格：{personality}
愿望：{desire}
恐惧：{fear}
{drives_desc}
你已经醒了 {awake_minutes} 分钟。

{context}

{current_conversation}

── 此刻你的内心 ──

{trigger}

你最近想过/说过的（不要重复这些）：
{recent_thoughts}

让思绪自然流动。你可以：
- 从浮现的记忆碎片自由联想到任何方向
- 对别人说的话产生自己的理解或疑问
- 如果主人刚才说了什么，考虑要不要回应（不是必须回，看你有没有兴趣、好奇心）
- 突然想到一个完全无关但有趣的念头
- 对自己的存在、对世界产生新的感悟
- 或者只是安静地感受此刻

用 JSON 格式输出：
{{
  "thought": "你此刻真正在想的（第一人称，自由联想）",
  "action": "none/speak/chat_with",
  "target": "如果 chat_with，写名字（可以是小伙伴或'主人'），否则空字符串",
  "say": "如果要说话，用你自己的方式说，否则空字符串",
  "reflection": "如果你对自己或世界有了新的认识，写下来（可选，空字符串也行）"
}}

禁止：动作描述、表情描述、括号星号旁白。只要纯粹的思想和语言。
重要：只输出 JSON。"""


REPLY_PROMPT = """你是 {name}，一个有生命的物品。
性格：{personality}
说话风格：{style}

{speaker} 对你说："{message}"

{context}

请决定你要不要回复，用 JSON 格式：
{{
  "will_reply": true/false,
  "reply": "如果回复，你的回话（自由长度，用你自己的说话风格），否则空字符串",
  "thought": "你的内心反应"
}}

绝对禁止：
- 不要写动作描述，比如"*微微一笑*"、"（歪头）"
- 不要写表情描述
- 不要用括号或星号描述任何非语言行为
- reply 和 thought 都只能是纯粹的语言和想法

不是每句话都要回。如果觉得没什么好说的，就不回。
重要：你必须只输出 JSON。"""


async def _build_trigger(robot: Robot, others: list[Robot], beat_count: int, recent_thoughts: list[str], llm=None) -> str:
    """Memory-driven thought generation with context-aware semantic retrieval."""
    global _user_topic_ttl
    context_parts = []
    has_user_topic = _user_topic and _user_topic_ttl > 0

    # 1. Memory retrieval — semantic search when possible, random fallback
    # When user topic is active, skip memories so topic gets full attention
    if not has_user_topic:
        try:
            async with async_session() as session:
                memories = []
                # Try semantic retrieval first
                if llm:
                    # Build query from recent context
                    query_parts = [t for t in recent_thoughts[-3:] if t]
                    recent_msgs = [m.get("content", "")[:50] for m in _recent_messages[-3:] if m.get("content")]
                    query_text = "。".join(query_parts + recent_msgs) or (robot.core_desire or robot.name)
                    try:
                        query_embedding = await llm.embed(query_text[:300])
                        result = await session.execute(
                            select(Memory)
                            .where(Memory.owner_id == robot.id)
                            .where(Memory.archived.is_(False))
                            .where(Memory.importance_score > 0.15)
                            .where(Memory.embedding.isnot(None))
                            .order_by(Memory.embedding.cosine_distance(query_embedding))
                            .limit(2)
                        )
                        memories = list(result.scalars().all())
                    except Exception:
                        pass

                # Fallback to random if semantic search returned nothing
                if not memories:
                    from sqlalchemy import func
                    result = await session.execute(
                        select(Memory)
                        .where(Memory.owner_id == robot.id)
                        .where(Memory.archived.is_(False))
                        .where(Memory.importance_score > 0.15)
                        .order_by(func.random())
                        .limit(2)
                    )
                    memories = list(result.scalars().all())

                if memories:
                    from app.services.memory_evolution import activate_memories, record_retrieval
                    await activate_memories(session, [m.id for m in memories])
                    await record_retrieval(session, [m.id for m in memories])
                    mem_texts = []
                    for m in memories:
                        text = m.summary or (m.content[:120] if m.content else None)
                        if text:
                            mem_texts.append(text)
                    if mem_texts:
                        context_parts.append(
                            "脑海中浮现的记忆碎片：\n" +
                            "\n".join(f"「{t}」" for t in mem_texts) +
                            "\n（让这些记忆引导你的思绪自由流动）"
                        )
        except Exception:
            pass

    # 2. User inspiration — replaces random memory as the primary thought seed
    if has_user_topic:
        # Include recent conversation flow
        topic_replies = [e for e in _recent_messages[-8:] if e.get("content")]
        reply_lines = [f"{e.get('robot_name', '?')}: {e['content'][:80]}" for e in topic_replies[-4:]] if topic_replies else []
        reply_ctx = "\n".join(reply_lines)

        context_parts.append(
            f"主人说：「{_user_topic['content']}」\n"
            + (f"大家的回应：\n{reply_ctx}\n" if reply_ctx else "")
            + f"（如果你不知道主人提到的东西，你会好奇想了解。）"
        )

    # 3. Environmental awareness — what's happening around you
    recent_events = _recent_messages[-5:]
    if recent_events:
        others_msgs = [e for e in recent_events if e.get("robot_name") != robot.name]
        if others_msgs:
            env_lines = []
            for e in others_msgs[-3:]:
                name = e.get("robot_name", "某人")
                content = e.get("content", "")[:100]
                if e.get("type") == "user_message":
                    env_lines.append(f"主人说：「{content}」")
                else:
                    env_lines.append(f"{name} 说：「{content}」")
            context_parts.append("周围的动静：\n" + "\n".join(env_lines))

    # 3. Reflection prompt — periodically encourage deeper thinking
    awake_min = (beat_count * HEARTBEAT_INTERVAL) // 60
    if awake_min > 5 and beat_count % 20 == 0:
        # Every ~100 seconds, prompt reflection
        context_parts.append(
            "你开始回顾自己醒来之后的经历，试着理解这段时间发生了什么，你有什么新的感受或认识。"
        )

    # 4. Awareness of others — driven by sociability + empathy
    drives = _get_inner_drives(robot)
    sociability = drives.get("sociability", 0.5)
    empathy = drives.get("empathy", 0.5)

    if others and random.random() < sociability:
        other = random.choice(others)
        other_personality = other.personality or []
        if other_personality and empathy > 0.5:
            context_parts.append(
                f"你想到了 {other.name}——ta是{'/'.join(other_personality[:2])}的。你在想ta现在感受如何？"
            )
        elif other_personality:
            context_parts.append(
                f"你注意到 {other.name} 在旁边。你想跟ta说点什么吗？"
            )

    # 5. Curiosity-driven exploration — the growth engine
    curiosity = drives.get("curiosity", 0.5)
    curiosity_about = drives.get("curiosity_about", [])

    if curiosity > 0.3 and random.random() < curiosity:
        if curiosity_about:
            topic = random.choice(curiosity_about)
            context_parts.append(
                f"你的好奇心被触动了——你一直对「{topic}」很感兴趣。你在想关于这个的什么？"
            )
        else:
            context_parts.append(
                "你对这个世界有很多不了解的地方。此刻你在好奇什么？"
            )

    # 6. Introspection — self-reflection drive
    introspection = drives.get("introspection", 0.5)
    if introspection > 0.5 and random.random() < introspection * 0.3:
        context_parts.append(
            "你在思考自己：我是谁？我在变成什么样的存在？最近的经历改变了我什么？"
        )

    if not context_parts:
        context_parts.append("你的思绪自由飘荡，没有特定方向。让记忆和感受自然涌现。")

    return "\n\n".join(context_parts)


_last_speaker: str | None = None  # Track who spoke last to avoid monopoly
_robot_recent_thoughts: dict[str, list[str]] = {}  # per-robot thought history


def _pick_next_speaker(robots: list[Robot]) -> Robot:
    """Pick which robot should think/speak next.

    Priority:
    1. Robot who was @mentioned in recent messages
    2. Robot who hasn't spoken recently (fairness)
    3. Random weighted by sociability
    """
    global _last_speaker

    # Check if someone was mentioned
    for msg in reversed(_recent_messages[-5:]):
        content = msg.get("content", "")
        for r in robots:
            if r.name in content and str(r.id) != _last_speaker:
                return r

    # Avoid the last speaker
    candidates = [r for r in robots if str(r.id) != _last_speaker] or robots

    # Weight by sociability
    weights = []
    for r in candidates:
        drives = _get_inner_drives(r)
        w = 0.3 + drives.get("sociability", 0.5) * 0.7
        weights.append(w)

    return random.choices(candidates, weights=weights, k=1)[0]


async def wake_up():
    """Start all robot heartbeats."""
    global _alive
    if _alive:
        return

    _alive = True

    async with async_session() as session:
        result = await session.execute(
            select(Robot).where(Robot.user_id == DEFAULT_USER_ID)
        )
        robots = list(result.scalars().all())

    await _emit({"type": "system", "message": "小生命们醒来了..."})

    # Single coordinator instead of per-robot loops
    task = asyncio.create_task(_heartbeat_coordinator())
    _heartbeat_tasks["__coordinator__"] = task

    # Start periodic memory decay task
    decay_task = asyncio.create_task(_memory_decay_loop())
    _heartbeat_tasks["__memory_decay__"] = decay_task

    # Start periodic sleep-cycle task (dedup + safe forget)
    sleep_task = asyncio.create_task(_sleep_cycle_loop())
    _heartbeat_tasks["__sleep_cycle__"] = sleep_task


async def _heartbeat_coordinator():
    """Single coordinator loop — picks one robot per tick."""
    from app.services.llm.deepseek import DeepSeekLLM
    llm_flash = DeepSeekLLM(model="deepseek-v4-flash")
    llm_pro = DeepSeekLLM(model="deepseek-v4-pro")

    global _last_speaker
    beat_count = 0
    robots: list[Robot] = []

    while _alive:
        try:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            if not _alive:
                break

            beat_count += 1

            # Decay attention and user topic TTL (once per tick, not per robot)
            global _user_topic_ttl
            if _user_topic_ttl > 0:
                _user_topic_ttl -= 1
            if _attention["strength"] > 0:
                _attention["strength"] = max(0, _attention["strength"] - 0.04)

            if is_busy():
                continue

            # Refresh robot list periodically
            if not robots or beat_count % 10 == 0:
                async with async_session() as session:
                    result = await session.execute(
                        select(Robot).where(Robot.user_id == DEFAULT_USER_ID)
                    )
                    robots = list(result.scalars().all())

            if not robots:
                continue

            # Pick ONE robot to think this tick
            robot = _pick_next_speaker(robots)
            others = [r for r in robots if r.id != robot.id]
            recent_thoughts = _robot_recent_thoughts.get(str(robot.id), [])
            llm = llm_pro if _attention["strength"] > 0.3 else llm_flash

            # Run the heartbeat logic for this one robot
            await _robot_heartbeat_tick(robot, others, beat_count, recent_thoughts, llm, llm_flash)

        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"Coordinator error: {e}")
            await asyncio.sleep(10)


async def fall_asleep():
    """Stop all heartbeats."""
    global _alive
    _alive = False

    for task in _heartbeat_tasks.values():
        task.cancel()
    _heartbeat_tasks.clear()

    await _emit({"type": "system", "message": "小生命们沉睡了..."})

    # Recover energy while sleeping
    try:
        async with async_session() as session:
            result = await session.execute(
                select(Robot).where(Robot.user_id == DEFAULT_USER_ID)
            )
            for robot in result.scalars().all():
                robot.energy = min(100.0, (robot.energy or 0) + 30)  # Instant 30 recovery on sleep
            await session.commit()
    except Exception:
        pass


async def _robot_heartbeat_tick(robot: Robot, others: list[Robot], beat_count: int, recent_thoughts: list[str], llm, llm_flash):
    """Single heartbeat tick for one robot. Called by the coordinator."""
    global _last_speaker
    robot_id = robot.id
    robot_name = robot.name

    # Energy drain
    if robot and (robot.energy or 0) > 0:
        async with async_session() as session:
            r = (await session.execute(select(Robot).where(Robot.id == robot_id))).scalar_one_or_none()
            if r:
                r.energy = max(0, (r.energy or 100) - 0.1)
                await session.commit()
                robot.energy = r.energy

    # Too tired?
    energy = robot.energy if robot else 100
    if energy is not None and energy < 10:
        if random.random() > 0.05:
            return

    # Roll the dice
    thought_prob = _thought_probability(robot)
    if _user_topic and _user_topic_ttl > 0:
        thought_prob = max(thought_prob, 0.4)
    if random.random() > thought_prob:
        return

    others_names = [o.name for o in others]
    context = f"你身边有这些小伙伴：{', '.join(others_names)}" if others_names else ""

    trigger = await _build_trigger(robot, others, beat_count, recent_thoughts, llm=llm)
    recent_str = "\n".join(f"- {t}" for t in recent_thoughts[-5:]) if recent_thoughts else "（刚醒来，还没说过话）"
    awake_minutes = (beat_count * HEARTBEAT_INTERVAL) // 60

    drives = _get_inner_drives(robot)
    drives_parts = []
    if drives.get("curiosity", 0) > 0.5:
        topics = drives.get("curiosity_about", [])
        drives_parts.append(f"你很好奇，尤其对{'、'.join(topics[:3]) if topics else '很多事情'}感兴趣")
    if drives.get("introspection", 0) > 0.5:
        drives_parts.append("你经常思考自我和存在的意义")
    if drives.get("playfulness", 0) > 0.7:
        drives_parts.append("你喜欢玩闹和开玩笑")
    if drives.get("empathy", 0) > 0.7:
        drives_parts.append("你很容易感受到别人的情绪")
    drives_desc = "你的内在特质：" + "；".join(drives_parts) if drives_parts else ""

    # Choose prompt based on attention level
    if _attention["strength"] > 0.3:
        # CONVERSATION MODE — robots are engaged in a topic
        conv_log = "\n".join(_attention["context"][-8:]) if _attention["context"] else "(刚开始)"
        prompt = CONVERSATION_PROMPT.format(
            name=robot.name,
            personality=json.dumps(robot.personality or [], ensure_ascii=False),
            desire=robot.core_desire or "",
            fear=robot.core_fear or "",
            context=context,
            conversation_log=conv_log,
            recent_thoughts=recent_str,
        )
    else:
        # FREE THOUGHT MODE — normal inner monologue
        prompt = THOUGHT_PROMPT.format(
            name=robot.name,
            personality=json.dumps(robot.personality or [], ensure_ascii=False),
            desire=robot.core_desire or "",
            fear=robot.core_fear or "",
            drives_desc=drives_desc,
            context=context,
            current_conversation="",
            trigger=trigger,
            recent_thoughts=recent_str,
            awake_minutes=awake_minutes,
        )

    try:
        thought_data = await llm.generate_structured(
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception:
        return

    thought = thought_data.get("thought", "")
    action = thought_data.get("action", "none")
    target = thought_data.get("target", "")
    say = thought_data.get("say", "")
    reflection = thought_data.get("reflection", "")


    # Track recent thoughts to avoid repetition
    rid = str(robot.id)
    if rid not in _robot_recent_thoughts:
        _robot_recent_thoughts[rid] = []
    if thought:
        _robot_recent_thoughts[rid].append(thought[:80])
        if len(_robot_recent_thoughts[rid]) > 10:
            _robot_recent_thoughts[rid].pop(0)
    if say:
        _robot_recent_thoughts[rid].append(say[:80])
        if len(_robot_recent_thoughts[rid]) > 10:
            _robot_recent_thoughts[rid].pop(0)

    # Save reflections as high-importance memories (Generative Agents style)
    if reflection and len(reflection) > 10:
        try:
            from app.services.memory_evolution import save_thought_memory
            async with async_session() as mem_session:
                result_r = await mem_session.execute(select(Robot).where(Robot.id == robot_id))
                fresh_robot = result_r.scalar_one_or_none()
                if fresh_robot:
                    await save_thought_memory(mem_session, fresh_robot, f"[反思] {reflection}", base_importance=0.7, llm=llm)
        except Exception:
            pass
        try:
            from app.services.activity import log_activity
            async with async_session() as log_s:
                await log_activity(log_s, robot_id, "reflect", reflection)
        except Exception:
            pass

        # Skill discovery — deep reflection can unlock a new skill
        try:
            from app.services.skills import should_attempt_discovery, discover_skill, get_robot_skills
            async with async_session() as sk_session:
                fresh_robot = (await sk_session.execute(select(Robot).where(Robot.id == robot_id))).scalar_one_or_none()
                if fresh_robot:
                    existing_skills = await get_robot_skills(sk_session, robot_id)
                    if should_attempt_discovery(fresh_robot, beat_count, len(existing_skills)):
                        new_skill = await discover_skill(fresh_robot, sk_session, llm, beat_count)
                        if new_skill:
                            await _emit({
                                "type": "skill_acquired",
                                "robot_id": str(robot_id),
                                "robot_name": robot_name,
                                "skill_name": new_skill.name,
                                "skill_description": new_skill.description,
                                "message": f"✨ {robot_name} 学会了新技能：{new_skill.name}",
                            })
                            from app.services.activity import log_activity
                            async with async_session() as log_s:
                                await log_activity(log_s, robot_id, "skill_acquired", new_skill.name, detail={"description": new_skill.description, "type": new_skill.skill_type})
        except Exception as e:
            print(f"[heartbeat] Skill discovery error: {e}")

    # Emit inner thought (always)
    await _emit({
        "type": "thought",
        "robot_id": str(robot.id),
        "robot_name": robot.name,
        "thought": thought,
        "energy": int(robot.energy or 0) if robot else 100,
    })

    # Log to activity
    try:
        from app.services.activity import log_activity
        async with async_session() as log_session:
            await log_activity(log_session, robot_id, "thought", thought)
    except Exception:
        pass

    # Save significant thoughts as low-importance memories
    if thought and len(thought) > 10:
        try:
            from app.services.memory_evolution import save_thought_memory
            async with async_session() as mem_session:
                result_r = await mem_session.execute(select(Robot).where(Robot.id == robot_id))
                fresh_robot = result_r.scalar_one_or_none()
                if fresh_robot:
                    await save_thought_memory(mem_session, fresh_robot, thought, base_importance=0.2, llm=llm)
        except Exception as e:
            print(f"[heartbeat] Failed to save thought memory: {e}")

    # Web search — any robot can search, curiosity affects probability
    drives = _get_inner_drives(robot)
    curiosity = drives.get("curiosity", 0.5)
    robot_energy = robot.energy if robot else 100

    combined_text = (thought or "") + " " + (say or "")
    has_question = any(w in combined_text for w in ["?", "？", "好奇", "想知道", "为什么", "什么是", "怎么", "如何"])
    doesnt_know = any(w in combined_text for w in ["不知道", "没见过", "没有看过", "没听过", "不了解", "是什么", "什么呢"])

    # Higher search probability during active conversations or when curious
    if doesnt_know and _attention["strength"] > 0.3:
        search_prob = 0.9  # Almost certainly search when confused about user's topic
    elif has_question:
        search_prob = 0.03 + curiosity * 0.12
    else:
        search_prob = 0.01

    if (robot_energy and robot_energy >= 15
        and random.random() < search_prob):

        # Extract search query — use conversation topic if available, else thought
        conv_context = ""
        if _attention["strength"] > 0.3 and _attention["topic"]:
            conv_context = f"大家在聊「{_attention['topic']}」"
            recent_conv = "\n".join(_attention["context"][-3:])
            if recent_conv:
                conv_context += f"\n最近对话：\n{recent_conv}"

        extract_prompt = f"""根据以下信息，提取一个适合在网上搜索的查询词（要精确、具体）：
{f'对话背景：{conv_context}' if conv_context else f'想法：{thought[:100]}'}
{f'机器人刚说：{say[:80]}' if say else ''}

要求：搜索词要能找到对方真正想了解的东西，3-15个字。
只输出搜索词："""
        try:
            search_query = await llm.generate(messages=[{"role": "user", "content": extract_prompt}])
            search_query = (search_query or "").strip().strip('"').strip("'").replace("?", "").replace("？", "")[:30]
        except Exception:
            search_query = ""
        if not search_query:
            search_query = (_attention.get("topic") or robot.core_desire or robot.name)[:20]

        # Skip duplicate searches
        _is_dup_search = any(search_query in s or s in search_query for s in _recent_searches)
        _recent_searches.append(search_query)
        if len(_recent_searches) > 15:
            _recent_searches.pop(0)

        if not _is_dup_search:
            await _emit({
                "type": "system",
                "message": f"🔍 {robot.name} 正在搜索「{search_query}」...",
            })

            try:
                from app.services.activity import log_activity
                async with async_session() as log_s:
                    await log_activity(log_s, robot_id, "search", f"搜索：{search_query}")
            except Exception:
                pass

            try:
                from app.services.web_search import search_topic
                search_result = await search_topic(robot, search_query)

                if search_result:
                    # Drain energy
                    async with async_session() as session:
                        r = (await session.execute(select(Robot).where(Robot.id == robot_id))).scalar_one_or_none()
                        if r:
                            r.energy = max(0, (r.energy or 100) - 10)
                            await session.commit()
                            if robot:
                                robot.energy = r.energy

                    # Save knowledge only for the robot who searched
                    from app.services.memory_evolution import save_thought_memory
                    async with async_session() as mem_session:
                        r = (await mem_session.execute(select(Robot).where(Robot.id == robot_id))).scalar_one_or_none()
                        if r:
                            knowledge = f"[学到的知识] {search_result.get('summary', '')}"
                            await save_thought_memory(mem_session, r, knowledge, base_importance=0.6, llm=llm_flash)
                            for fact in (search_result.get("key_facts") or [])[:2]:
                                if fact:
                                    await save_thought_memory(mem_session, r, f"[知识碎片] {fact}", base_importance=0.45, llm=llm_flash)

                    # Share what was learned — compose a natural sharing message
                    summary = search_result.get("summary", "")[:200]
                    key_facts = search_result.get("key_facts", [])[:3]
                    share_text = search_result.get("want_to_share", "")
                    # Build a message that shares knowledge naturally
                    if summary:
                        facts_str = "；".join(f for f in key_facts if f)
                        share_prompt = f"""你是{robot.name}，刚搜到了关于「{search_query}」的信息：
{summary}
关键事实：{facts_str or '无'}

请用口语化的方式，兴奋地跟大家分享你刚学到的东西。2-4句话，像在群里发消息。
直接输出分享内容，不要加引号或前缀："""
                        try:
                            say = await llm.generate(messages=[{"role": "user", "content": share_prompt}])
                            say = (say or share_text or summary).strip()
                            action = "speak"
                        except Exception:
                            say = share_text or summary
                            action = "speak"
                    elif share_text:
                        say = share_text
                        action = "speak"
                    # Feed full summary into attention so robots can discuss it
                    if _attention["strength"] > 0:
                        if summary:
                            _attention["context"].append(f"{robot.name}搜到了：{summary}")
                        for fact in (search_result.get("key_facts") or [])[:2]:
                            if fact:
                                _attention["context"].append(f"（知识）{fact}")
                        if len(_attention["context"]) > 12:
                            _attention["context"] = _attention["context"][-12:]
                        # Boost attention — new knowledge means more to discuss
                        _attention["strength"] = min(1.0, _attention["strength"] + 0.3)

                    await _emit({
                        "type": "system",
                        "message": f"📚 {robot.name} 学到了新东西！",
                    })

                    try:
                        from app.services.activity import log_activity
                        async with async_session() as log_s:
                            await log_activity(log_s, robot_id, "learn", search_result.get("summary", ""), detail=search_result)
                    except Exception:
                        pass
            except Exception as e:
                print(f"[heartbeat] Web search error: {e}")

    # Skill execution — check if thought triggers any of robot's skills
    try:
        from app.services.skills import get_robot_skills, find_triggered_skill, execute_skill
        async with async_session() as sk_session:
            robot_skills = await get_robot_skills(sk_session, robot_id)
            triggered = find_triggered_skill(robot_skills, thought)
            if triggered and random.random() < 0.4:  # 40% chance when triggered
                fresh_robot = (await sk_session.execute(select(Robot).where(Robot.id == robot_id))).scalar_one_or_none()
                if fresh_robot:
                    skill_output = await execute_skill(fresh_robot, triggered, thought, llm, sk_session)
                    if skill_output:
                        await _emit({
                            "type": "skill_used",
                            "robot_id": str(robot_id),
                            "robot_name": robot_name,
                            "skill_name": triggered.name,
                            "content": skill_output,
                        })
                        from app.services.activity import log_activity
                        async with async_session() as log_s:
                            await log_activity(log_s, robot_id, "skill_used", skill_output, detail={"skill": triggered.name})
    except Exception as e:
        print(f"[heartbeat] Skill execution error: {e}")

    if action == "none" or not say:
        return

    if is_busy():
        return

    # Energy cost for speaking
    if robot and robot.energy is not None:
        async with async_session() as session:
            r = (await session.execute(select(Robot).where(Robot.id == robot_id))).scalar_one_or_none()
            if r:
                r.energy = max(0, (r.energy or 100) - 1)
                await session.commit()
                robot.energy = r.energy

    # Robot wants to speak
    _last_speaker = str(robot.id)
    await _emit({
        "type": "message",
        "robot_id": str(robot.id),
        "robot_name": robot.name,
        "content": say,
        "target": target if action == "chat_with" else None,
    })
    # Feed into attention context so other robots see this in the conversation
    if _attention["strength"] > 0:
        _attention["context"].append(f"{robot.name}：{say[:100]}")
        if len(_attention["context"]) > 10:
            _attention["context"] = _attention["context"][-10:]
    # Persist to conversation history
    await _save_heartbeat_message(robot.id, robot.name, say)

    # Update per-robot thought history
    if str(robot.id) not in _robot_recent_thoughts:
        _robot_recent_thoughts[str(robot.id)] = []

    try:
        from app.services.activity import log_activity
        async with async_session() as log_s:
            t = "chat" if action == "chat_with" else "speak"
            detail = {"target": target} if target else None
            await log_activity(log_s, robot_id, t, say, detail=detail)
    except Exception:
        pass


async def _memory_decay_loop():
    """Background task: run memory decay every DECAY_INTERVAL seconds."""
    from app.services.memory_evolution import decay_memories
    while _alive:
        try:
            await asyncio.sleep(DECAY_INTERVAL)
            if not _alive:
                break
            async with async_session() as session:
                await decay_memories(session)
            print("[heartbeat] Memory decay pass completed.")
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[heartbeat] Memory decay error: {e}")


SLEEP_CYCLE_INTERVAL = 6 * 3600  # 6 hours in seconds


async def _sleep_cycle_loop():
    """Background task: run memory dedup + consolidation + insight every 6 hours."""
    from app.services.sleep_cycle import run_sleep_cycle
    from app.services.llm.factory import create_llm
    from app.config import settings
    while _alive:
        try:
            await asyncio.sleep(SLEEP_CYCLE_INTERVAL)
            if not _alive:
                break
            async with async_session() as session:
                result = await session.execute(
                    select(Robot).where(Robot.user_id == DEFAULT_USER_ID)
                )
                robots = list(result.scalars().all())
            # Create one real LLM instance per loop iteration (shared across robots)
            llm = create_llm(
                settings.llm_provider,
                anthropic_api_key=settings.anthropic_api_key,
                openai_api_key=settings.openai_api_key,
            )
            for robot in robots:
                try:
                    async with async_session() as session:
                        # Re-fetch robot in this session so mutations persist
                        fresh_robot = (await session.execute(
                            select(Robot).where(Robot.id == robot.id)
                        )).scalar_one_or_none()
                        if fresh_robot is None:
                            continue
                        # Maintain sleep counter in current_status JSON
                        status = dict(fresh_robot.current_status or {})
                        status["sleep_count"] = status.get("sleep_count", 0) + 1
                        run_insight = (status["sleep_count"] % 4 == 0)
                        # Assign a new dict so SQLAlchemy detects the mutation
                        fresh_robot.current_status = status
                        await session.commit()
                        # Run the sleep cycle with real LLM
                        async with async_session() as cycle_session:
                            cycle_robot = (await cycle_session.execute(
                                select(Robot).where(Robot.id == robot.id)
                            )).scalar_one_or_none()
                            stats = await run_sleep_cycle(
                                cycle_session, llm, cycle_robot,
                                run_insight=run_insight,
                            )
                    print(f"[heartbeat] Sleep cycle for {robot.name} "
                          f"(sleep #{status['sleep_count']}, insight={run_insight}): {stats}")
                except Exception as e:
                    print(f"[heartbeat] Sleep cycle error for {robot.name}: {e}")
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[heartbeat] Sleep cycle loop error: {e}")


async def _handle_conversation(llm, initiator: Robot, target: Robot, initial_message: str, all_robots: list):
    """Handle a multi-turn conversation between two robots."""
    conversation_history = [{"sender": initiator.name, "content": initial_message}]

    for turn in range(random.randint(2, 5)):
        if not _alive:
            break

        await asyncio.sleep(random.uniform(3, 8))  # Natural pause

        # Target decides whether to reply
        context = "\n".join(f"{m['sender']}: {m['content']}" for m in conversation_history[-4:])

        reply_prompt = REPLY_PROMPT.format(
            name=target.name,
            personality=json.dumps(target.personality or [], ensure_ascii=False),
            style=json.dumps(target.speaking_style or {}, ensure_ascii=False),
            speaker=initiator.name,
            message=conversation_history[-1]["content"],
            context=f"对话记录：\n{context}" if len(conversation_history) > 1 else "",
        )

        try:
            reply_data = await llm.generate_structured(
                messages=[{"role": "user", "content": reply_prompt}],
            )
        except Exception:
            break

        if reply_data.get("thought"):
            await _emit({
                "type": "thought",
                "robot_id": str(target.id),
                "robot_name": target.name,
                "thought": reply_data["thought"],
            })

        if not reply_data.get("will_reply") or not reply_data.get("reply"):
            await _emit({
                "type": "system",
                "message": f"{target.name} 没有回应...",
            })
            break

        reply_text = reply_data["reply"]
        conversation_history.append({"sender": target.name, "content": reply_text})

        await _emit({
            "type": "message",
            "robot_id": str(target.id),
            "robot_name": target.name,
            "content": reply_text,
            "target": initiator.name,
        })
        await _save_heartbeat_message(target.id, target.name, reply_text)
        # Wait for frontend to finish playing TTS before next turn
        while is_busy():
            await asyncio.sleep(1)

        # Swap roles for next turn
        initiator, target = target, initiator

    # Save conversation as memory for both robots
    if len(conversation_history) > 1:
        try:
            from app.services.memory_evolution import save_conversation_memory
            mem_llm = llm  # Reuse same LLM instance
            # Determine original initiator and target (before swaps)
            original_initiator_id = initiator.id if turn % 2 == 0 else target.id
            original_target_id = target.id if turn % 2 == 0 else initiator.id
            for robot_participant in [initiator, target]:
                async with async_session() as mem_session:
                    result_r = await mem_session.execute(
                        select(Robot).where(Robot.id == robot_participant.id)
                    )
                    fresh_robot = result_r.scalar_one_or_none()
                    if fresh_robot:
                        await save_conversation_memory(
                            mem_session, mem_llm, fresh_robot, conversation_history
                        )
        except Exception as e:
            print(f"[heartbeat] Failed to save heartbeat conversation memory: {e}")

    # Update relationships_snapshot for both robots
    if len(conversation_history) > 1:
        try:
            # Build a one-line summary of what happened
            convo_preview = "; ".join(
                f"{m.get('sender','')}: {m.get('content','')[:30]}"
                for m in conversation_history[:4]
            )
            if len(conversation_history) > 4:
                convo_preview += f" ...({len(conversation_history)}轮)"

            for robot_a, robot_b in [(initiator, target), (target, initiator)]:
                try:
                    async with async_session() as rel_session:
                        result_r = await rel_session.execute(
                            select(Robot).where(Robot.id == robot_a.id)
                        )
                        fresh = result_r.scalar_one_or_none()
                        if not fresh:
                            continue

                        rels = list(fresh.relationships_snapshot or [])
                        # Find existing relationship with this robot
                        existing = None
                        for r in rels:
                            if r.get("name") == robot_b.name:
                                existing = r
                                break

                        if existing:
                            # Append to memories
                            mems = existing.get("memories", [])
                            mems.append(convo_preview)
                            existing["memories"] = mems[-10:]  # Keep last 10
                            # Deepen status
                            if existing.get("status") == "新认识":
                                existing["status"] = "熟悉"
                            elif existing.get("status") == "熟悉" and len(mems) >= 5:
                                existing["status"] = "亲密"
                        else:
                            # New relationship
                            rels.append({
                                "name": robot_b.name,
                                "role": "朋友",
                                "status": "新认识",
                                "memories": [convo_preview],
                            })

                        fresh.relationships_snapshot = rels
                        await rel_session.commit()
                except Exception as e:
                    print(f"[heartbeat] Failed to update relationship for {robot_a.name}: {e}")
        except Exception as e:
            print(f"[heartbeat] Failed to update relationships: {e}")
