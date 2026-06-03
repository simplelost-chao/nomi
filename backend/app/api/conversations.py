import random
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.engine import get_session
from app.db.models import Conversation, Message, Robot
from app.prompts.director import build_speaker_prompt
from app.schemas import ConversationOut, MessageOut, UserMessageRequest

router = APIRouter(prefix="/api/conversations", tags=["conversations"])

DEFAULT_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

AVAILABLE_MODELS = {
    "deepseek-v4-flash": {"label": "DeepSeek V4 Flash", "provider": "deepseek"},
    "deepseek-v4-pro": {"label": "DeepSeek V4 Pro", "provider": "deepseek"},
    "qwen2.5:7b": {"label": "Qwen 2.5 7B (本地)", "provider": "ollama"},
    "claude": {"label": "Claude (CLI)", "provider": "claude-cli"},
}


def _create_chat_llm(model: str):
    if model.startswith("deepseek"):
        from app.services.llm.deepseek import DeepSeekLLM
        return DeepSeekLLM(model=model)
    elif model.startswith("qwen") or model.startswith("llama"):
        from app.services.llm.ollama import OllamaLLM
        return OllamaLLM(model=model)
    else:
        from app.services.llm.claude_cli import ClaudeCliLLM
        return ClaudeCliLLM()


@router.get("/models")
async def list_models():
    return [{"id": k, **v} for k, v in AVAILABLE_MODELS.items()]


@router.delete("/all")
async def clear_all_conversations(session: AsyncSession = Depends(get_session)):
    """Delete all conversations and messages."""
    from sqlalchemy import delete as sa_delete
    await session.execute(sa_delete(Message))
    await session.execute(sa_delete(Conversation))
    await session.commit()
    # Reset heartbeat attention
    from app.services.heartbeat import _attention, _recent_messages
    _attention["topic"] = None
    _attention["strength"] = 0.0
    _attention["context"] = []
    _recent_messages.clear()
    return {"deleted": True}


@router.get("/latest")
async def get_latest_conversation(session: AsyncSession = Depends(get_session)):
    """Get the most recent conversation with its messages."""
    result = await session.execute(
        select(Conversation)
        .where(Conversation.user_id == DEFAULT_USER_ID)
        .order_by(Conversation.created_at.desc())
        .limit(1)
    )
    conv = result.scalar_one_or_none()
    if not conv:
        return None
    msgs = await session.execute(
        select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)
    )
    return {
        "id": str(conv.id),
        "messages": [_msg_dict(m) for m in msgs.scalars().all()],
    }


@router.post("", response_model=ConversationOut)
async def create_conversation(session: AsyncSession = Depends(get_session)):
    conversation = Conversation(user_id=DEFAULT_USER_ID, conversation_type="user_chat")
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)
    # Tell heartbeat to use this conversation too
    from app.services.heartbeat import set_shared_conversation
    set_shared_conversation(conversation.id)
    return conversation


@router.post("/{conversation_id}/message")
async def send_message(
    conversation_id: uuid.UUID,
    body: UserMessageRequest,
    model: str = Query(default="deepseek-v4-flash"),
    robot_id: str = Query(default=""),
    session: AsyncSession = Depends(get_session),
):
    conv_result = await session.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conversation = conv_result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Sync conversation ID with heartbeat + inject user message into heartbeat context
    from app.services.heartbeat import set_shared_conversation, inject_user_message
    set_shared_conversation(conversation_id)
    inject_user_message("主人", body.content)

    # Save user message
    user_msg = Message(
        conversation_id=conversation_id,
        sender_type="user",
        sender_id=DEFAULT_USER_ID,
        sender_name="主人",
        content=body.content,
    )
    session.add(user_msg)
    await session.commit()
    await session.refresh(user_msg)

    # Get robots (filter to single robot if robot_id specified)
    if robot_id:
        robot_result = await session.execute(
            select(Robot).where(Robot.id == uuid.UUID(robot_id))
        )
    else:
        robot_result = await session.execute(
            select(Robot).where(Robot.user_id == DEFAULT_USER_ID)
        )
    robots = list(robot_result.scalars().all())
    if not robots:
        return {"messages": [_msg_dict(user_msg)], "timing": {}}

    llm = _create_chat_llm(model)
    model_info = AVAILABLE_MODELS.get(model, {"label": model})

    # Build context
    msg_result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(20)
    )
    recent_messages = list(reversed(msg_result.scalars().all()))
    conversation_so_far = [
        {"sender": m.sender_name or "unknown", "content": m.content or ""}
        for m in recent_messages
    ]

    # All robots respond in PARALLEL
    import asyncio

    response_messages = [_msg_dict(user_msg)]

    # Retrieve relevant memories for each robot based on user's message
    user_query_embedding = None
    try:
        user_query_embedding = await llm.embed(body.content[:300])
    except Exception:
        pass

    async def _get_robot_memories(robot_id) -> list[str]:
        """Get relevant memories for a robot via semantic search."""
        if not user_query_embedding:
            return []
        try:
            mem_result = await session.execute(
                select(Memory)
                .where(Memory.owner_id == robot_id)
                .where(Memory.embedding.isnot(None))
                .order_by(Memory.embedding.cosine_distance(user_query_embedding))
                .limit(5)
            )
            mems = mem_result.scalars().all()
            return [m.summary or (m.content[:100] if m.content else "") for m in mems if m.summary or m.content]
        except Exception:
            return []

    # Pre-fetch memories sequentially (session is not concurrent-safe)
    robot_memories_map: dict = {}
    for robot in robots:
        robot_memories_map[robot.id] = await _get_robot_memories(robot.id)

    async def _generate_reply(robot: Robot) -> tuple[Robot, str, int]:
        robot_memories = robot_memories_map.get(robot.id, [])
        system, prompt = build_speaker_prompt(
            robot_name=robot.name,
            robot_personality=robot.personality or [],
            origin_story=robot.origin_story or "",
            speaking_style=robot.speaking_style or {},
            memories=robot_memories,
            relationships=[],
            conversation_so_far=conversation_so_far,
            director_note="Respond naturally to the user's message.",
        )
        # Prepend robot's custom system_prompt if set
        if robot.system_prompt:
            system = robot.system_prompt + "\n\n" + system
        t0 = time.time()
        content = await llm.generate(
            messages=[{"role": "user", "content": prompt}],
            system_prompt=system,
        )
        llm_time_ms = int((time.time() - t0) * 1000)
        return robot, content, llm_time_ms

    # Fire all LLM calls simultaneously
    results = await asyncio.gather(*[_generate_reply(r) for r in robots], return_exceptions=True)

    total_llm_ms = 0
    for result in results:
        if isinstance(result, Exception):
            print(f"[conversations] Robot reply error: {result}")
            continue
        robot, content, llm_time_ms = result
        total_llm_ms = max(total_llm_ms, llm_time_ms)  # Wall time = max, not sum

        robot_msg = Message(
            conversation_id=conversation_id,
            sender_type="robot",
            sender_id=robot.id,
            sender_name=robot.name,
            content=content,
            metadata_={"model": model, "llm_time_ms": llm_time_ms},
        )
        session.add(robot_msg)
        await session.commit()
        await session.refresh(robot_msg)
        response_messages.append(_msg_dict(robot_msg))
        conversation_so_far.append({"sender": robot.name, "content": content})

        # Feed reply into heartbeat context so subsequent heartbeats see the conversation
        from app.services.heartbeat import _recent_messages
        _recent_messages.append({"type": "message", "robot_name": robot.name, "content": content})
        if len(_recent_messages) > 20:
            _recent_messages.pop(0)

    # Memory evolution (async, use dedicated session)
    from app.db.engine import async_session as _async_session
    _robot_ids = [r.id for r in robots]
    _convo = list(conversation_so_far)

    async def _evolve_memories():
        try:
            from app.services.memory_evolution import save_conversation_memory, check_evolution
            from app.services.llm.deepseek import DeepSeekLLM
            from sqlalchemy import select as _sel
            from app.db.models import Robot as _Robot
            mem_llm = DeepSeekLLM(model="deepseek-v4-flash")
            async with _async_session() as bg_session:
                for rid in _robot_ids:
                    r = await bg_session.execute(_sel(_Robot).where(_Robot.id == rid))
                    robot = r.scalar_one_or_none()
                    if robot:
                        await save_conversation_memory(bg_session, mem_llm, robot, _convo)
                        await check_evolution(bg_session, mem_llm, robot)
        except Exception as e:
            print(f"[conversations] Memory evolution error: {e}")

    asyncio.create_task(_evolve_memories())

    return {
        "messages": response_messages,
        "timing": {
            "model": model,
            "model_label": model_info.get("label", model),
            "total_llm_ms": total_llm_ms,
            "robot_count": len(robots),
        },
    }


def _msg_dict(msg: Message) -> dict:
    return {
        "id": str(msg.id),
        "sender_type": msg.sender_type,
        "sender_id": str(msg.sender_id) if msg.sender_id else None,
        "sender_name": msg.sender_name,
        "content": msg.content,
        "emotion": msg.emotion,
        "created_at": msg.created_at.isoformat(),
        "metadata": msg.metadata_,
    }


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
async def get_messages(conversation_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at)
    )
    return list(result.scalars().all())
