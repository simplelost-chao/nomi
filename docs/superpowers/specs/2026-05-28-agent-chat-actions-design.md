# Agent Chat with Actions — Design Spec

**Goal:** Let users chat with characters who can seamlessly decide to use tools (search, open browser, notify) via LLM function calling, inspired by Shinsekai's recursive tool-call loop.

## Architecture

```
User sends message
  → Desktop → POST /api/agents/chat
  → Backend builds system prompt + tool definitions
  → DeepSeek (function calling enabled)
  → LLM decides: plain reply OR tool_call
      ├─ Plain reply → return { reply, emotion, desktop_actions: [] }
      └─ tool_call →
          ├─ Backend tool (web_search) → execute → feed result back → LLM generates final reply
          └─ Desktop tool (open_browser, notify) → mark as desktop_action → LLM generates reply assuming it will be executed
```

## Tool Definitions

### Backend-executed tools (results feed back to LLM)

| Tool | Description | Params |
|------|-------------|--------|
| `web_search` | 后台搜索，结果喂回LLM让角色转述 | `query: string` |

### Desktop-executed tools (returned to client for execution)

| Tool | Description | Params |
|------|-------------|--------|
| `open_browser` | 打开浏览器访问URL或搜索 | `url: string` |
| `notify` | 弹系统通知 | `title: string, body: string` |

## Backend Endpoint

**`POST /api/agents/chat`**

Request:
```json
{
  "robot_id": "uuid",
  "message": "帮我搜一下明天天气",
  "conversation_id": "uuid (optional, for context)"
}
```

Response:
```json
{
  "reply": "查到了，明天晴天28度，适合出门哦～",
  "reply_ja": "調べたよ、明日は晴れで28度、お出かけ日和だね～",
  "emotion": "Happy",
  "desktop_actions": [
    {"type": "open_browser", "params": {"url": "https://..."}}
  ],
  "tool_calls_made": ["web_search"]
}
```

### Implementation Flow

1. Look up robot, build character system prompt (reuse `build_speaker_prompt`)
2. Append tool instructions to system prompt
3. Build conversation context (last 20 messages from conversation_id if provided)
4. Call DeepSeek with `tools` parameter (OpenAI function calling)
5. **Recursive loop** (like Shinsekai):
   - If LLM returns `tool_calls`:
     - Backend tools (`web_search`): execute, add tool result message, call LLM again
     - Desktop tools (`open_browser`, `notify`): collect into `desktop_actions`, add fake success result, call LLM again
   - If LLM returns plain text: done, parse reply
6. Save user message + bot reply to conversation (reuse existing Message model)
7. Return response

### Tool Definitions for DeepSeek

```python
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
```

## Desktop Integration

### Changes to `api.ts`

Add `agentChat` method that calls `/api/agents/chat`.

### Changes to `App.tsx`

Modify `handleSend`:
- Always use `/api/agents/chat` (replaces the regular conversation endpoint for desktop)
- On response: show reply as chat bubble, play TTS, execute `desktop_actions`
- Desktop actions executed via existing `action-manager.ts` (already has `open_url` and `notify`)

### Conversation Persistence

The new endpoint saves messages to the existing `Message` table, so conversation history is preserved and available for context in subsequent messages.

## Edge Cases

- **No tools needed**: LLM just replies normally, zero overhead (tools param is just metadata)
- **Multiple tool calls**: LLM can call multiple tools in one turn, all get executed
- **Tool failure**: Return error message as tool result, LLM adapts ("抱歉搜索失败了")
- **Max recursion**: Cap at 3 tool-call rounds to prevent infinite loops
