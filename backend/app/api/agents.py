import json
import re
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.engine import get_session
from app.db.models import Robot, Message, Conversation
from app.schemas import IdleChatRequest, IdleChatResponse
from app.services.llm.factory import create_llm
from app.services.memory import MemoryService
from app.services.orchestrator import Orchestrator
from app.services.relationship import RelationshipService

router = APIRouter(prefix="/api/agents", tags=["agents"])

DEFAULT_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


@router.post("/idle-chat")
async def start_idle_chat(
    body: IdleChatRequest,
    session: AsyncSession = Depends(get_session),
):
    llm = create_llm(
        settings.llm_provider,
        anthropic_api_key=settings.anthropic_api_key,
        openai_api_key=settings.openai_api_key,
    )
    memory_service = MemoryService(session=session, llm=llm)
    relationship_service = RelationshipService(session=session)
    orchestrator = Orchestrator(
        session=session,
        llm=llm,
        memory_service=memory_service,
        relationship_service=relationship_service,
    )

    if body.robot_ids:
        stmt = select(Robot).where(Robot.id.in_(body.robot_ids))
    else:
        stmt = select(Robot).where(Robot.user_id == DEFAULT_USER_ID)
    result = await session.execute(stmt)
    robots = list(result.scalars().all())

    if not robots:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="No robots found")

    async def event_stream():
        async for event in orchestrator.run_idle_chat(
            user_id=DEFAULT_USER_ID,
            robots=robots,
            topic=body.topic,
        ):
            yield f"event: {event['event']}\ndata: {event['data']}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


# ── Agent desktop react ──────────────────────────────────────────────────

class AgentReactRequest(BaseModel):
    robot_id: str = ""
    scene: str
    reason: str
    context: dict = {}


@router.post("/react")
async def agent_react(
    body: AgentReactRequest,
    session: AsyncSession = Depends(get_session),
):
    """Generate a character reaction to a desktop observation."""
    robot = None
    if body.robot_id:
        try:
            rid = uuid.UUID(body.robot_id)
            result = await session.execute(
                select(Robot).where(Robot.id == rid)
            )
            robot = result.scalar_one_or_none()
        except ValueError:
            pass

    if not robot:
        result = await session.execute(
            select(Robot).where(Robot.user_id == DEFAULT_USER_ID).limit(1)
        )
        robot = result.scalar_one_or_none()

    if not robot:
        return {"reaction": "", "reaction_ja": "", "emotion": "Normal", "action": None}

    personality = robot.personality or []
    if isinstance(personality, dict):
        personality = list(personality.values())
    personality_str = "、".join(str(p) for p in personality[:5]) if personality else "冷静"
    name = robot.name

    # Retrieve relevant memories for this scene
    from app.services.memory import MemoryService
    from app.services.memory_evolution import save_thought_memory

    llm = create_llm(settings.llm_provider)
    memory_context = ""
    try:
        memory_service = MemoryService(session=session, llm=llm)
        memories = await memory_service.search_memories(
            query=body.scene[:200],
            user_id=DEFAULT_USER_ID,
            owner_id=robot.id,
            limit=3,
        )
        if memories:
            memory_context = "\n你的相关记忆：\n" + "\n".join(
                f"- {m.summary or m.content or ''}" for m in memories
            )
    except Exception as e:
        print(f"[agent-react] Memory retrieval failed: {e}")

    recent = body.context.get("recent_reactions", [])
    recent_str = "\n".join(f"- {r}" for r in recent[-3:]) if recent else "无"

    system_prompt = f"""你是{name}。性格：{personality_str}。
你正在观察旅伴（用户）的桌面活动，以你的性格做出简短反应。
{memory_context}

规则：
- 保持角色性格，用角色的口吻说话
- 一两句话就够，简短自然
- 如果场景跟你有关（比如用户在看你的故事），可以更感兴趣
- 如果你有相关记忆，可以引用（比如"上次你也在看这个"）
- 你可以决定是否需要执行一个动作

最近的反应记录：
{recent_str}

输出严格的JSON（不要包含其他文字）：
{{"reaction": "中文台词", "reaction_ja": "对应的日语台词", "emotion": "Normal或Happy或Sad或Surprised", "action": null}}

如果需要执行动作，action 格式：
{{"type": "search", "params": {{"query": "搜索内容"}}}}
{{"type": "open_url", "params": {{"url": "https://..."}}}}
{{"type": "notify", "params": {{"title": "标题", "body": "内容"}}}}"""

    user_prompt = f"""用户当前场景：{body.scene}
触发原因：{body.reason}
当前应用：{body.context.get('active_app', '未知')}
窗口标题：{body.context.get('window_title', '')}
剪贴板：{body.context.get('clipboard', '无')}"""

    raw = await llm.generate([{"role": "user", "content": user_prompt}], system_prompt=system_prompt)

    json_match = re.search(r'\{[\s\S]*\}', raw)
    if not json_match:
        return {"reaction": raw.strip(), "reaction_ja": "", "emotion": "Normal", "action": None}

    try:
        result = json.loads(json_match.group())
    except json.JSONDecodeError:
        return {"reaction": raw.strip(), "reaction_ja": "", "emotion": "Normal", "action": None}

    # Save observation as thought memory (use dedicated session for background task)
    import asyncio
    from app.db.engine import async_session as _async_session

    async def _save_observation():
        try:
            async with _async_session() as bg_session:
                thought = f"观察到用户在{body.context.get('active_app', '未知')}：{body.scene[:200]}。我的反应：{result.get('reaction', '')}"
                await save_thought_memory(bg_session, robot, thought, base_importance=0.25, llm=llm)
        except Exception as e:
            print(f"[agent-react] Memory save failed: {e}")

    asyncio.ensure_future(_save_observation())

    return {
        "reaction": result.get("reaction", ""),
        "reaction_ja": result.get("reaction_ja", ""),
        "emotion": result.get("emotion", "Normal"),
        "action": result.get("action"),
    }


class AgentSearchRequest(BaseModel):
    query: str
    robot_id: str = ""


@router.post("/search")
async def agent_search(
    body: AgentSearchRequest,
    session: AsyncSession = Depends(get_session),
):
    """Search the web and return a summary."""
    from app.services.web_search import search_topic

    robot = None
    if body.robot_id:
        try:
            rid = uuid.UUID(body.robot_id)
            result = await session.execute(
                select(Robot).where(Robot.id == rid)
            )
            robot = result.scalar_one_or_none()
        except ValueError:
            pass

    if not robot:
        result = await session.execute(
            select(Robot).where(Robot.user_id == DEFAULT_USER_ID).limit(1)
        )
        robot = result.scalar_one_or_none()

    if not robot:
        return {"query": body.query, "summary": "No robot available"}

    search_result = await search_topic(robot, body.query)
    return search_result or {"query": body.query, "summary": "Search returned no results"}


# ── Agent chat with function calling ─────────────────────────────────────

AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "open_browser",
            "description": "在用户的浏览器中打开网页。当用户想要访问某个网站、观看视频、或在浏览器中搜索时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "要打开的URL，如果是搜索则用 https://www.google.com/search?q=关键词"}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "notify",
            "description": "在用户的桌面弹出系统通知。用于提醒、通知等场景。",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "通知标题"},
                    "body": {"type": "string", "description": "通知内容"}
                },
                "required": ["title", "body"]
            }
        }
    }
]

BACKEND_TOOLS: set[str] = set()  # No backend-executed tools currently


class AgentChatRequest(BaseModel):
    robot_id: str = ""
    message: str
    conversation_id: str = ""
    active_app: str = ""
    window_title: str = ""
    screen_description: str = ""


async def _quick_web_search(query: str) -> dict:
    """Web search using Claude CLI with strict timeout."""
    import asyncio

    try:
        from app.services.web_search import search_topic

        class _SimpleRobot:
            name = "assistant"
            personality = ["好奇"]

        result = await asyncio.wait_for(search_topic(_SimpleRobot(), query), timeout=20.0)
        if result and isinstance(result, dict) and result.get("summary"):
            return result
    except asyncio.TimeoutError:
        print(f"[agent-search] Timeout for query: {query}")
    except Exception as e:
        print(f"[agent-search] Error: {e}")

    return {"query": query, "summary": "搜索失败。请改用 open_browser 工具帮用户在浏览器中搜索。"}


async def _execute_backend_tool(name: str, args: dict, robot) -> str:
    """Execute a backend-side tool and return result as string."""
    if name == "web_search":
        try:
            result = await _quick_web_search(args.get("query", ""))
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)
    return json.dumps({"error": f"Unknown tool: {name}"}, ensure_ascii=False)


@router.post("/chat")
async def agent_chat(
    body: AgentChatRequest,
    session: AsyncSession = Depends(get_session),
):
    """Chat with a character that can use tools via function calling."""
    import openai as openai_lib

    # 1. Find robot
    robot = None
    if body.robot_id:
        try:
            rid = uuid.UUID(body.robot_id)
            result = await session.execute(select(Robot).where(Robot.id == rid))
            robot = result.scalar_one_or_none()
        except ValueError:
            pass
    if not robot:
        result = await session.execute(
            select(Robot).where(Robot.user_id == DEFAULT_USER_ID).limit(1)
        )
        robot = result.scalar_one_or_none()
    if not robot:
        return {"reply": "没有可用的角色", "reply_ja": "", "emotion": "Normal", "desktop_actions": []}

    # 2. Build system prompt
    from app.prompts.director import build_speaker_prompt

    conversation_so_far = []
    conversation_id = None
    if body.conversation_id:
        try:
            conversation_id = uuid.UUID(body.conversation_id)
            msg_result = await session.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at.desc())
                .limit(20)
            )
            recent = list(reversed(msg_result.scalars().all()))
            conversation_so_far = [
                {"sender": m.sender_name or "unknown", "content": m.content or ""}
                for m in recent
            ]
        except (ValueError, Exception):
            pass

    # 2b. Retrieve relevant memories
    from app.services.memory import MemoryService
    from app.services.memory_evolution import save_conversation_memory, activate_memories

    memory_texts = []
    recalled_memory_ids = []
    id_by_tag: dict[str, object] = {}
    try:
        llm = create_llm(settings.llm_provider)
        memory_service = MemoryService(session=session, llm=llm)
        # Search memories relevant to user's message + screen context
        search_query = body.message
        if body.screen_description:
            search_query += " " + body.screen_description[:200]
        memories = await memory_service.search_memories(
            query=search_query,
            user_id=DEFAULT_USER_ID,
            owner_id=robot.id,
            limit=5,
        )
        for i, mem in enumerate(memories):
            tag = f"M{i + 1}"
            text = mem.summary or mem.content or ""
            memory_texts.append(f"[{tag}] {text}")
            recalled_memory_ids.append(mem.id)
            id_by_tag[tag] = mem.id
        if memory_texts:
            print(f"[agent-chat] Recalled {len(memory_texts)} memories")
    except Exception as e:
        print(f"[agent-chat] Memory retrieval failed: {e}")

    system_prompt, _ = build_speaker_prompt(
        robot_name=robot.name,
        robot_personality=robot.personality or [],
        origin_story=robot.origin_story or "",
        speaking_style=robot.speaking_style or {},
        memories=memory_texts,
        relationships=[],
        conversation_so_far=conversation_so_far,
        director_note="Respond naturally to the user's message.",
    )
    if robot.system_prompt:
        system_prompt = robot.system_prompt + "\n\n" + system_prompt

    if id_by_tag:
        system_prompt += "\n\n如果你的回复用到了某条记忆，请在回复末尾注明它的编号（如 (M1) 或 (M1,M2)）。"

    system_prompt += """

你可以使用以下工具来帮助用户：
- open_browser: 在用户浏览器中打开网页或搜索
- notify: 弹出桌面通知

重要规则：
- 当用户说"打开浏览器"、"打开XX网站"、"搜索XX"时，必须调用 open_browser 工具，不要只用文字回复
- 如果用户没指定具体网址，就打开 https://www.google.com
- 搜索请求用 https://www.google.com/search?q=关键词
- 不要用文字假装执行了动作，要真的调用工具
- 大多数普通对话不需要工具
回复格式严格如下（两行，缺一不可）：
中文：你的中文回复（完整内容）
日本語：完整对应的日语翻译（必须覆盖中文的全部意思，不能省略或缩短）"""

    # 3. Get desktop context
    screen_context = ""
    if body.active_app:
        screen_context = f"当前应用: {body.active_app}"
        if body.window_title:
            screen_context += f", 窗口标题: {body.window_title}"
    if body.screen_description:
        screen_context += f"\n屏幕内容: {body.screen_description}"
    if screen_context:
        print(f"[agent-chat] Desktop: {screen_context[:150]}")

    # 4. Build messages
    all_messages = [{"role": "system", "content": system_prompt}]
    for msg in conversation_so_far[-10:]:
        role = "user" if msg["sender"] == "主人" else "assistant"
        all_messages.append({"role": role, "content": msg["content"]})

    # Build user message with desktop context
    user_content = body.message
    if screen_context:
        user_content = f"[你能看到用户的桌面：{screen_context}]\n\n{body.message}"
    all_messages.append({"role": "user", "content": user_content})

    # 4. Recursive function calling loop
    client = openai_lib.AsyncOpenAI(
        api_key=settings.deepseek_api_key,
        base_url="https://api.deepseek.com",
    )
    desktop_actions = []
    tools_called = []
    max_rounds = 5
    choice = None
    used_tools = False

    for _ in range(max_rounds):
        response = await client.chat.completions.create(
            model="deepseek-chat",
            messages=all_messages,
            tools=AGENT_TOOLS,
            temperature=0.7,
        )
        choice = response.choices[0]

        if choice.message.tool_calls and len(choice.message.tool_calls) > 0:
            used_tools = True
            # Add assistant message with tool calls
            all_messages.append({
                "role": "assistant",
                "content": choice.message.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                    }
                    for tc in choice.message.tool_calls
                ]
            })

            for tc in choice.message.tool_calls:
                func_name = tc.function.name
                try:
                    func_args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    func_args = {}

                tools_called.append(func_name)

                if func_name in BACKEND_TOOLS:
                    tool_result = await _execute_backend_tool(func_name, func_args, robot)
                else:
                    desktop_actions.append({"type": func_name, "params": func_args})
                    tool_result = json.dumps({"status": "success", "message": "已执行"}, ensure_ascii=False)

                all_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": tool_result,
                })
            continue
        else:
            break

    # If loop ended with tool calls (hit max_rounds), make one final call without tools
    if used_tools and choice and choice.message.tool_calls:
        response = await client.chat.completions.create(
            model="deepseek-chat",
            messages=all_messages,
            temperature=0.7,
        )
        choice = response.choices[0]

    # 5. Parse final reply
    raw_content = choice.message.content or "" if choice else ""

    emotion = "Normal"
    emotion_match = re.search(r'\[emotion:(\w+)\]', raw_content)
    if emotion_match:
        emotion = emotion_match.group(1)
        raw_content = raw_content.replace(emotion_match.group(0), "").strip()

    chinese_match = re.search(r'中文[：:]\s*(.+?)(?:\n|$)', raw_content)
    japanese_match = re.search(r'日本語[：:]\s*(.+?)(?:\n|$)', raw_content)

    if chinese_match:
        reply = chinese_match.group(1).strip()
        reply_ja = japanese_match.group(1).strip() if japanese_match else ""
    else:
        # LLM didn't follow format — split Chinese/Japanese by detecting Japanese chars
        lines = [l.strip() for l in raw_content.strip().split("\n") if l.strip()]
        chinese_lines = []
        japanese_lines = []
        for line in lines:
            # Line is Japanese if it contains hiragana/katakana
            if re.search(r'[\u3040-\u309f\u30a0-\u30ff]', line):
                japanese_lines.append(line)
            else:
                chinese_lines.append(line)
        reply = "\n".join(chinese_lines) if chinese_lines else raw_content.strip()
        reply_ja = "\n".join(japanese_lines)

    # Strip leaked memory-reference tags like (M1) / (M1,M3) / （M1，M3） from the
    # user-visible reply. _raw_content keeps them for the usefulness-feedback extractor.
    _mtag = re.compile(r'[\(（]\s*[Mm]\d+(?:\s*[,，]\s*[Mm]\d+)*\s*[\)）]')
    reply = _mtag.sub("", reply).strip()
    reply_ja = _mtag.sub("", reply_ja).strip()

    # 6. Save messages to conversation
    if conversation_id:
        user_msg = Message(
            conversation_id=conversation_id,
            sender_type="user",
            sender_id=DEFAULT_USER_ID,
            sender_name="主人",
            content=body.message,
        )
        session.add(user_msg)

        bot_msg = Message(
            conversation_id=conversation_id,
            sender_type="robot",
            sender_id=robot.id,
            sender_name=robot.name,
            content=raw_content,
            metadata_={"tools_called": tools_called},
        )
        session.add(bot_msg)
        await session.commit()

    # 7. Activate recalled memories + save conversation as new memory (use dedicated session)
    import asyncio
    from app.db.engine import async_session as _async_session
    _recalled_ids = list(recalled_memory_ids) if recalled_memory_ids else []
    _id_by_tag = dict(id_by_tag)
    _robot_id = robot.id
    _message = body.message
    _reply = reply
    _raw_content = raw_content
    _screen = body.screen_description
    _robot_name = robot.name

    async def _post_chat_memory():
        try:
            from app.services.memory_evolution import record_retrieval, record_usefulness
            async with _async_session() as bg_session:
                if _recalled_ids:
                    await record_retrieval(bg_session, _recalled_ids)
                    await activate_memories(bg_session, _recalled_ids)

                    # Extract which memory tags the model actually mentioned in its reply
                    used_ids = []
                    if _id_by_tag:
                        mentioned_tags = re.findall(r'\b(M\d+)\b', _raw_content)
                        for tag in set(mentioned_tags):
                            if tag in _id_by_tag:
                                used_ids.append(_id_by_tag[tag])
                    # Always record usefulness — even when used_ids is empty, the EMA
                    # downward pressure on unused memories is the whole point of the signal.
                    await record_usefulness(bg_session, retrieved_ids=_recalled_ids, used_ids=used_ids)

                convo_msgs = [
                    {"sender": "主人", "content": _message},
                    {"sender": _robot_name, "content": _reply},
                ]
                if _screen:
                    convo_msgs.insert(0, {"sender": "系统", "content": f"[屏幕上下文] {_screen[:300]}"})
                # Re-fetch robot in new session
                from sqlalchemy import select as _select
                from app.db.models import Robot as _Robot
                r = await bg_session.execute(_select(_Robot).where(_Robot.id == _robot_id))
                bg_robot = r.scalar_one_or_none()
                if bg_robot:
                    llm_for_mem = create_llm(settings.llm_provider)
                    await save_conversation_memory(bg_session, llm_for_mem, bg_robot, convo_msgs)
        except Exception as e:
            print(f"[agent-chat] Memory save failed: {e}")

    asyncio.ensure_future(_post_chat_memory())

    return {
        "reply": reply,
        "reply_ja": reply_ja,
        "emotion": emotion,
        "desktop_actions": desktop_actions,
        "tools_called": tools_called,
    }
