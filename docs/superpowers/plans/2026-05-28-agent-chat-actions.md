# Agent Chat with Actions — Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Replace the desktop chat flow with function-calling-enabled `/api/agents/chat` endpoint so characters can seamlessly use tools.

**Spec:** `docs/superpowers/specs/2026-05-28-agent-chat-actions-design.md`

---

### Task 1: Backend — `/api/agents/chat` endpoint with function calling

**Files:**
- Modify: `backend/app/api/agents.py`

- [ ] **Step 1: Add tool definitions and chat endpoint**

Add after existing endpoints in `agents.py`:

```python
# ── Agent chat with function calling ─────────────────────────────────────

AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "在网上搜索信息，结果会返回给你。当用户想知道某个事实、新闻、天气等信息时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"}
                },
                "required": ["query"]
            }
        }
    },
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

# Tools that execute on backend (results feed back to LLM)
BACKEND_TOOLS = {"web_search"}

class AgentChatRequest(BaseModel):
    robot_id: str = ""
    message: str
    conversation_id: str = ""


async def _execute_backend_tool(name: str, args: dict, robot) -> str:
    """Execute a backend-side tool and return result as string."""
    if name == "web_search":
        try:
            from app.services.web_search import search_topic
            result = await search_topic(robot, args.get("query", ""))
            if result and isinstance(result, dict):
                return json.dumps(result, ensure_ascii=False)
            return json.dumps({"summary": "搜索没有返回结果"}, ensure_ascii=False)
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
    from app.db.models import Message, Conversation

    # Get conversation context if provided
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

    system_prompt, _ = build_speaker_prompt(
        robot_name=robot.name,
        robot_personality=robot.personality or [],
        origin_story=robot.origin_story or "",
        speaking_style=robot.speaking_style or {},
        memories=[],
        relationships=[],
        conversation_so_far=conversation_so_far,
        director_note="Respond naturally to the user's message.",
    )
    if robot.system_prompt:
        system_prompt = robot.system_prompt + "\n\n" + system_prompt

    # Append tool usage instructions
    system_prompt += """

你可以使用以下工具来帮助用户：
- web_search: 搜索信息（结果会返回给你，你用自己的话转述）
- open_browser: 在用户浏览器中打开网页
- notify: 弹出桌面通知

根据用户的意图自然地决定是否需要使用工具。大多数普通对话不需要工具。
回复格式保持你的角色风格，包含中文和日语：
中文：你的回复
日本語：对应的日语"""

    # 3. Build messages for DeepSeek
    all_messages = [{"role": "system", "content": system_prompt}]
    for msg in conversation_so_far[-10:]:
        role = "user" if msg["sender"] == "主人" else "assistant"
        all_messages.append({"role": role, "content": msg["content"]})
    all_messages.append({"role": "user", "content": body.message})

    # 4. Recursive function calling loop
    client = openai_lib.AsyncOpenAI(
        api_key=settings.deepseek_api_key or "sk-REDACTED",
        base_url="https://api.deepseek.com",
    )
    desktop_actions = []
    tools_called = []
    max_rounds = 3

    for _ in range(max_rounds):
        response = await client.chat.completions.create(
            model="deepseek-chat",
            messages=all_messages,
            tools=AGENT_TOOLS,
            temperature=0.7,
        )

        choice = response.choices[0]

        if choice.finish_reason == "tool_calls" or (choice.message.tool_calls and len(choice.message.tool_calls) > 0):
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
                    # Execute on backend, feed result back
                    tool_result = await _execute_backend_tool(func_name, func_args, robot)
                else:
                    # Desktop tool — collect action, return success to LLM
                    desktop_actions.append({"type": func_name, "params": func_args})
                    tool_result = json.dumps({"status": "success", "message": "已执行"}, ensure_ascii=False)

                all_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": tool_result,
                })
            # Loop again to get final reply
            continue
        else:
            # Plain text reply — we're done
            break

    # 5. Parse final reply
    raw_content = choice.message.content or ""
    from app.api.conversations import _msg_dict

    # Parse emotion/chinese/japanese from the reply
    emotion = "Normal"
    emotion_match = re.search(r'\[emotion:(\w+)\]', raw_content)
    if emotion_match:
        emotion = emotion_match.group(1)
        raw_content = raw_content.replace(emotion_match.group(0), "").strip()

    chinese_match = re.search(r'中文[：:]\s*(.+?)(?:\n|$)', raw_content)
    japanese_match = re.search(r'日本語[：:]\s*(.+?)(?:\n|$)', raw_content)

    reply = chinese_match.group(1).strip() if chinese_match else raw_content.strip()
    reply_ja = japanese_match.group(1).strip() if japanese_match else ""

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

    return {
        "reply": reply,
        "reply_ja": reply_ja,
        "emotion": emotion,
        "desktop_actions": desktop_actions,
        "tools_called": tools_called,
    }
```

- [ ] **Step 2: Add `deepseek_api_key` to settings if missing**

Check `backend/app/config.py` for `deepseek_api_key`. If not present, add it. The DeepSeek key is already hardcoded in `deepseek.py` as fallback.

- [ ] **Step 3: Verify backend starts**

Run: `cd /Users/chao/Documents/Projects/nomi && python -c "import ast; ast.parse(open('backend/app/api/agents.py').read()); print('OK')"`

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/agents.py
git commit -m "feat(agent): add /api/agents/chat with function calling"
```

---

### Task 2: Desktop — Switch chat flow to agent endpoint

**Files:**
- Modify: `desktop/src/renderer/api.ts`
- Modify: `desktop/src/renderer/App.tsx`

- [ ] **Step 1: Add `agentChat` to api.ts**

Add to the `api` object:

```typescript
agentChat: (message: string, robotId: string, conversationId?: string) => {
  const body: Record<string, string> = { message, robot_id: robotId };
  if (conversationId) body.conversation_id = conversationId;
  return request<{
    reply: string;
    reply_ja: string;
    emotion: string;
    desktop_actions: Array<{ type: string; params: Record<string, string> }>;
    tools_called: string[];
  }>("/api/agents/chat", {
    method: "POST",
    body: JSON.stringify(body),
  });
},
```

- [ ] **Step 2: Modify `handleSend` in App.tsx**

Replace the current `handleSend` implementation to use `api.agentChat` instead of `api.sendMessage`. The new flow:

1. Call `api.agentChat(text, robot.id, conversationId)`
2. Create user message + bot message from response
3. Execute `desktop_actions` via the existing action-manager IPC:
   - `open_browser` → `shell.openExternal(url)` (add IPC handler)
   - `notify` → `new Notification(...)` (add IPC handler)
4. Play TTS with the reply

Key changes:
- Remove `parseBotReply` call (the endpoint returns parsed fields directly)
- Add desktop action execution after receiving response
- Show tool usage indicator (e.g., "🔍 搜索中..." while waiting)

- [ ] **Step 3: Add desktop action execution IPC**

In `desktop/src/preload/index.ts`, add to the agent namespace:

```typescript
executeAction: (action: { type: string; params: Record<string, string> }) =>
  ipcRenderer.invoke("agent:execute-action", action),
```

In `desktop/src/main/ipc.ts`, add handler:

```typescript
ipcMain.handle("agent:execute-action", async (_event, action) => {
  const { executeAction } = await import("./agent/action-manager");
  // Map open_browser to open_url for existing action manager
  if (action.type === "open_browser") {
    action.type = "open_url";
  }
  return executeAction(action);
});
```

- [ ] **Step 4: Update Window type in App.tsx**

Add `executeAction` to the `agent` type declaration.

- [ ] **Step 5: Build and test**

Run: `cd /Users/chao/Documents/Projects/nomi/desktop && npm run build`

- [ ] **Step 6: Commit**

```bash
git add desktop/src/renderer/api.ts desktop/src/renderer/App.tsx desktop/src/preload/index.ts desktop/src/main/ipc.ts
git commit -m "feat(agent): switch desktop chat to function-calling agent endpoint"
```

---

### Task 3: End-to-End Test

- [ ] **Step 1: Restart backend**

```bash
pm2 restart nomi-backend
```

- [ ] **Step 2: Build and launch desktop**

```bash
cd desktop && npm run build && npx electron .
```

- [ ] **Step 3: Test scenarios**

1. Normal chat: "你好" → plain reply, no tools
2. Info search: "帮我查一下明天天气" → web_search → character relays result
3. Open browser: "打开B站" → open_browser → browser opens + character says something
4. Browser search: "帮我在浏览器搜一下最新iPhone" → open_browser with search URL
5. Notification: "提醒我5分钟后喝水" → notify action

- [ ] **Step 4: Commit final state**
