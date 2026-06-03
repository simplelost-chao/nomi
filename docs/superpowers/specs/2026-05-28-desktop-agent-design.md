# Desktop Agent Design — Nomi Companion

**Date**: 2026-05-28
**Status**: Approved

## Overview

Transform the Nomi desktop companion from a chat-only interface into a full desktop agent that can perceive the user's screen, react in character, perform actions (search, open URLs, send notifications), and maintain the character's personality throughout.

## Core Principles

- **Role-playing first**: Agent always stays in character (Frieren, etc.) — calm, personality-consistent reactions
- **Dual-layer architecture**: Local model (Ollama) for fast perception filtering, cloud LLM for quality character expression
- **Privacy-aware**: Screenshots processed locally, only text descriptions sent to cloud
- **User in control**: Every capability has an independent on/off toggle

## Architecture

```
┌─ Electron Main Process ─────────────────────────┐
│                                                   │
│  ┌─ Sensor Manager ───────────────────────────┐  │
│  │  ScreenSensor    (截屏, 30s, 可配置)         │  │
│  │  ClipboardSensor (剪贴板变化监听)             │  │
│  │  AppSensor       (前台窗口变化检测)           │  │
│  │  每个 Sensor 有独立开关                       │  │
│  └──────────────────┬─────────────────────────┘  │
│                     ↓                             │
│  ┌─ Local Analyzer (Ollama) ──────────────────┐  │
│  │  截屏+上下文 → minicpm-v 本地分析             │  │
│  │  输出: { scene, interesting, reason }        │  │
│  │  不有趣 → 丢弃 (90%的截屏在此过滤)            │  │
│  │  有趣 → 发给后端                              │  │
│  └──────────────────┬─────────────────────────┘  │
│                     ↓                             │
│  ┌─ Action Manager ──────────────────────────┐   │
│  │  openBrowser(url)   webSearch(query)        │   │
│  │  openApp(name)      sendNotification(text)  │   │
│  │  readFile(path)                             │   │
│  └────────────────────────────────────────────┘   │
└───────────────────┬───────────────────────────────┘
                    ↓ IPC
┌─ Renderer (UI) ───────────────────────────────────┐
│  Avatar + ChatPanel + AgentSettings               │
│  混合显示: 主动反应 + 用户对话                       │
│  TTS 播放                                          │
└───────────────────────────────────────────────────┘
                    ↓ HTTP
┌─ Backend (FastAPI) ───────────────────────────────┐
│  POST /api/agent/react    感知结果 → 角色台词生成    │
│  POST /api/agent/search   搜索请求 → 返回结果       │
│  现有 TTS / LLM 管线                                │
└───────────────────────────────────────────────────┘
```

## Sensor Manager

### Sensors

| Sensor | 触发方式 | 数据 | 默认 |
|--------|---------|------|------|
| ScreenSensor | 定时截屏 (默认30s, 可配置10/30/60/120s) | PNG截图压缩到720p | 关 |
| ClipboardSensor | 监听剪贴板变化 | 文本(前100字)/图片 | 关 |
| AppSensor | 前台窗口变化检测 | 应用名 + 窗口标题 | 关 |

### Actions

| Action | 触发方式 | 默认 |
|--------|---------|------|
| WebSearch | 用户对话或LLM决策 | 开 |
| Notification | LLM决策 | 开 |
| FileAccess | 用户对话触发 | 关 |
| OpenURL/App | LLM决策或用户对话 | 开 |

### Design Points

- 每个 Sensor/Action 是独立类，统一接口 `{ type, data, timestamp }`
- 所有开关存在 `~/.nomi/agent-config.json`
- ScreenSensor 用 Electron `desktopCapturer` API
- 截屏前先做像素差异比较，变化 < 5% 直接跳过不调 Ollama

## Local Analyzer (Ollama)

### Model

- `minicpm-v` (3.1GB) — 轻量 vision 模型，Apple Silicon 上 2-4 秒/张
- 备选: `llava:7b` (4.7GB) — 更准但更大

### Analysis Flow

```
输入: {
  screenshot: base64_png (720p),
  active_app: "VS Code",
  window_title: "index.ts - nomi",
  clipboard_text: "...",
  last_scene: "用户在写代码"
}

→ Ollama prompt: "简要描述用户在做什么，判断是否值得评论"

→ 输出: {
  scene: "用户在VS Code写TypeScript代码",
  interesting: false,
  reason: "跟上次一样在写代码"
}
```

### Dedup & Rate Limiting

- 维护最近 5 次 scene 摘要，相似场景不重复触发
- 两次触发间隔最少 2 分钟 (可配置)
- 截屏前像素差异 < 5% 直接跳过

### Performance

- 分析一张 720p 截图约 2-4 秒 (Apple Silicon)
- ~90% 截屏被"不有趣"过滤掉
- 内存占用约 4-5GB

## Backend — `/api/agent/react`

### Request

```json
{
  "robot_id": "frieren-uuid",
  "scene": "用户在看动漫，画面是战斗场景",
  "reason": "用户从写代码切换到看动漫",
  "context": {
    "active_app": "Chrome",
    "window_title": "葬送のフリーレン EP20 - Bilibili",
    "clipboard": null,
    "recent_reactions": ["10分钟前评论了用户写代码"]
  }
}
```

### LLM System Prompt

```
你是フリーレン，千年精灵魔法使。用户是你的旅伴。
你正在观察用户的桌面活动，以你的性格做出简短反应。
规则：
- 保持角色性格（冷静、淡然、偶尔天然呆）
- 一两句话就够，不要长篇大论
- 如果用户在看跟你相关的内容，可以更感兴趣
- 可以决定是否需要执行动作（搜索、打开网页等）

输出 JSON:
{
  reaction: "中文台词",
  reaction_ja: "日语台词",
  emotion: "Normal/Happy/Sad/Surprised",
  action: null 或 { type: "search/open_url/notify", params: {...} }
}
```

### Response

```json
{
  "reaction": "嗯…你在看我的故事啊。这一集的战斗魔法其实很初级呢。",
  "reaction_ja": "ん…私の物語を見てるの。この回の戦闘魔法は実はとても初歩的なのよ。",
  "emotion": "Normal",
  "action": null
}
```

### Action Execution

LLM 返回 action 时，Electron 主进程执行:
- `search` → web search API → 结果返回给 LLM 再生成评论
- `open_url` → `shell.openExternal(url)`
- `notify` → `new Notification({ title, body })`

## UI Design

### Message Types in Chat Panel

- **用户对话** — 右侧气泡 (现有)
- **角色回复** — 左侧气泡 (现有)
- **主动反应** — 左侧气泡 + 淡紫色背景 + 👁 标识

### Settings Panel

从角色名旁边齿轮按钮打开，包含：
- 感知功能开关 (屏幕/剪贴板/应用切换) + 截屏频率
- 动作功能开关 (搜索/通知/文件/打开网页)
- 语音播放开关
- 最小打扰间隔

### Status Indicator

角色立绘下方小图标，显示: 空闲 / 👁感知中 / 🔍搜索中 / ⚡执行中

## Data Flow

```
1. 用户打开屏幕感知开关
2. ScreenSensor 定时截屏 (30s)
3. 像素差异检查 → 变化 < 5% 跳过
4. 压缩720p → Ollama 分析 (2-4s)
5. interesting: false → 丢弃 (大部分在此结束)
6. interesting: true → 去重 + 间隔检查
7. POST /api/agent/react → 云端LLM生成角色台词 (3-5s)
8. 返回 reaction → UI显示气泡 + Avatar切换表情
9. TTS合成日语 → 播放 (15-20s)
10. 如有 action → Action Manager 执行
11. 搜索结果 → 再次LLM生成评论
```

## Error Handling

| 场景 | 处理 |
|------|------|
| Ollama 没启动/崩溃 | 状态指示器❌，重试3次，失败后关闭感知并通知 |
| 后端不可用 | 主动反应暂停，对话显示"连接中"，30s重试 |
| CosyVoice 不可用 | 跳过语音只显示文字 |
| 截屏权限被拒 | 提示授权，屏幕感知自动关闭 |
| LLM返回格式错误 | 丢弃本次反应，记日志 |
| TTS太慢 | 文字先显示，语音异步不阻塞 |

## Privacy

- 截屏只在内存处理，不存盘
- Ollama 本地调用，不出网
- 发后端只有 scene 文字描述，不发截图
- 剪贴板只发摘要 (前100字)

## File Structure

```
desktop/src/main/
  agent/
    sensor-manager.ts        # 管理所有Sensor启停和调度
    screen-sensor.ts         # desktopCapturer截屏 + 像素差异
    clipboard-sensor.ts      # clipboard监听
    app-sensor.ts            # 前台窗口检测
    local-analyzer.ts        # Ollama HTTP调用 + 去重
    action-manager.ts        # 执行搜索/打开URL/通知/文件
    agent-config.ts          # 读写 ~/.nomi/agent-config.json
  index.ts                   # 新增agent初始化
  ipc.ts                     # 新增agent IPC通道

desktop/src/renderer/
  components/
    AgentSettings.tsx         # 设置面板
    ReactionBubble.tsx        # 主动反应气泡
    AgentStatus.tsx           # 状态指示器
  App.tsx                     # 集成agent状态

backend/app/api/
  agents.py                   # /api/agent/react, /api/agent/search
```

## IPC Channels

```typescript
// Main → Renderer
'agent:reaction'        // { text, text_ja, emotion, type: 'reaction' }
'agent:status'          // { status: 'idle'|'sensing'|'analyzing'|'speaking' }
'agent:action-result'   // { type: 'search', result: '...' }

// Renderer → Main
'agent:update-config'   // { screenSensor: true, interval: 30, ... }
'agent:get-config'      // → 返回当前配置
```

## Config File `~/.nomi/agent-config.json`

```json
{
  "screenSensor": { "enabled": false, "intervalSec": 30 },
  "clipboardSensor": { "enabled": false },
  "appSensor": { "enabled": false },
  "webSearch": { "enabled": true },
  "notification": { "enabled": true },
  "fileAccess": { "enabled": false },
  "openUrl": { "enabled": true },
  "voice": { "enabled": true },
  "minReactionIntervalSec": 120,
  "ollamaModel": "minicpm-v",
  "ollamaUrl": "http://localhost:11434"
}
```

## Dependencies

- Ollama + `minicpm-v` model (~3.1GB download)
- Electron `desktopCapturer` API
- Electron `clipboard` API
- macOS screen capture permission
