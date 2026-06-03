# Nomi 架构与功能详解

本文档面向想深入了解 Nomi 实现的开发者，覆盖系统组成、后端 API、数据模型、核心子系统设计与部署方式。项目概览与快速开始见根目录 [README](../README.md)。

---

## 1. 总览

Nomi 由四个可独立运行的部分组成，围绕一个 FastAPI 后端展开：

| 部分 | 目录 | 角色 |
|------|------|------|
| 后端 | `backend/` | 角色、记忆、心跳、Agent、TTS/STT 的全部业务逻辑与 API |
| Web 前端 | `frontend/` | 手机浏览器里的聊天 / 群聊界面 |
| 桌面 App | `desktop/` | 常驻桌面的 Live2D/立绘陪伴窗，含语音与桌面感知 |
| 语音服务 | 外部进程 | CosyVoice2（音色克隆）、Qwen3-TTS、faster-whisper |

后端支持两种部署形态：
- **云端模式**：PostgreSQL + pgvector，监听 `:8100`，供 Web 与桌面共用。
- **桌面单机模式**：SQLite（`~/.nomi/nomi.db`），监听 `127.0.0.1:18900`，入口 `backend/desktop/entrypoint.py`，无需 Redis。

---

## 2. 技术栈

- **后端**：FastAPI · Uvicorn · SQLAlchemy 2.0（async）· asyncpg / aiosqlite · pgvector · Pydantic Settings · Redis（可选）
- **Web**：Next.js 16 · React 19 · Tailwind CSS 4 · TypeScript
- **桌面**：Electron 35 · React 19 · Vite 6 · Tailwind 4 · pixi.js + pixi-live2d-display · TypeScript
- **AI**：Claude CLI / Anthropic / OpenAI / DeepSeek / Ollama / Google Gemini；嵌入用 Ollama `nomic-embed-text`
- **语音**：CosyVoice2-0.5B、Qwen3-TTS、edge-tts、faster-whisper

---

## 3. 后端 API 一览

基础前缀 `/api`，CORS 默认放行 `localhost:3100` 与生产域名。

### 角色 `/api/robots`
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/robots` | 列出角色（`?desktop=true` 过滤桌面可见） |
| POST | `/api/robots` | 批量创建角色 |
| GET/PATCH/DELETE | `/api/robots/{id}` | 读取 / 更新 / 删除角色 |
| POST | `/api/robots/from-image` | 从上传图片 + 文字提示异步生成角色 |
| GET | `/api/robots/creation-status/{job_id}` | 轮询生成进度 |
| GET | `/api/robots/{id}/activity` · `/skills` | 活动日志 / 已习得技能 |
| POST | `/api/robots/{id}/regenerate/{personality\|memories\|portrait}` | 重新生成人格 / 记忆 / 立绘 |

### 对话 `/api/conversations`
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/conversations` | 创建会话 |
| GET | `/api/conversations/latest` · `/{id}/messages` | 最近会话 / 历史消息 |
| POST | `/api/conversations/{id}/message` | 发送用户消息 → 所有角色并行回应 |
| GET | `/api/conversations/models` | 可用 LLM 模型列表 |

### Agent（桌面）`/api/agents`
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/agents/chat` | 带桌面上下文（当前应用、屏幕、剪贴板）的对话，支持函数调用 |
| POST | `/api/agents/react` | 观察桌面活动 → 角色情绪化反应（中/日文 + 可选动作） |
| POST | `/api/agents/search` | 角色网络搜索并总结 |
| POST(SSE) | `/api/agents/idle-chat` | 多角色自主群聊事件流 |

### 心跳 `/api/heartbeat`（群聊"内心世界"）
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/heartbeat/wake` · `/sleep` | 开启 / 关闭自主活动 |
| GET | `/api/heartbeat/status` · `/events?after=` | 状态 / 增量事件轮询 |
| POST | `/api/heartbeat/interval` · `/busy` | 设置节拍 / TTS 播放时暂停 |
| POST | `/api/heartbeat/trigger/{robot}/{action}` | 手动触发 thought/search/skill/reflect |

### 语音 `/api/tts` · `/api/stt`
| 方法 | 路径 | 引擎 |
|------|------|------|
| GET | `/api/tts/speak` | edge-tts（兜底） |
| GET | `/api/tts/speak-genie` | 按角色路由到 CosyVoice2 或 Qwen3 |
| GET/POST | `/api/tts/config` | 读取 / 切换 TTS 引擎 |
| POST | `/api/tts/regenerate/{robot_id}` | 在 CosyVoice 注册角色音色 |
| POST(file) | `/api/stt/transcribe` | faster-whisper 本地转写 |

### 其他
- `/api/objects/observe` — 提交图片/文字 → 角色反应并生成记忆。
- `/api/admin/*` — 角色与素材管理（Gemini 生图、抠图、音频上传、状态立绘版本）。
- `/api/health` · `/api/status` · `/admin`（管理面板 HTML）。

---

## 4. 数据模型

| 表 | 关键字段 | 说明 |
|----|---------|------|
| `users` | id, name, timezone | 用户 |
| `robots` | name, personality(JSON), voice_profile(JSON), energy, portrait(JSON), desktop_visible | 角色主体 |
| `yearly_memories` | robot_id, age, memory_content, importance, memory_strength | 角色成长记忆（按年龄） |
| `memories` | owner_id, content, embedding(768d), importance_score, emotional_tags | 可向量检索的短期记忆 |
| `conversations` | conversation_type, topic, summary | 会话 |
| `messages` | conversation_id, sender_type, content, emotion(JSON), metadata | 消息 |
| `robot_skills` | robot_id, name, trigger_keywords, execution_prompt | 习得技能 |
| `relationships` | subject_id, object_id, intimacy, trust, tension | 角色间关系 |
| `activity_logs` | robot_id, event_type, content, detail(JSON) | 行为审计 |
| `asset_versions` | robot_id, asset_type, asset_key, version, is_current | 立绘/语音版本管理 |
| `object_observations` | object_name, image_url, robot_reactions(JSON) | 桌面观察到的物体 |

关系：User 1:N Robot；Robot 1:N YearlyMemory / ActivityLog / RobotSkill；Conversation 1:N Message；Robot↔Robot 经 `relationships` 多对多。

---

## 5. 核心子系统

### 5.1 角色生成
从一张图片到完整角色：**识别外观 → 想象人格 → 批量生成成长记忆（每段 100–500 字）→ 合成完整人设 → 克隆音色**。视觉环节用 Google Gemini，文本环节用配置的 LLM。`voice_profile` 记录性别/年龄/音高/情绪范围等，用于指导 TTS。

### 5.2 记忆系统
- **写入**：对话结束后由 LLM 提炼"学到了什么"，存为 `Memory`（带情绪标签、重要度）。
- **检索**：查询文本 → 嵌入向量 → 在该角色的记忆里按余弦距离取 Top-K（PostgreSQL 用 pgvector；SQLite 退化为 Python/numpy 计算），注入到 prompt。
- **演化**：`memory_evolution` 周期性检查记忆积累是否应让角色人格发生偏移。

### 5.3 心跳系统（自主内心世界）
实现于 `app/services/heartbeat.py`。唤醒后按 N 秒（1–60，默认 5）一拍循环，每拍可能触发：
1. **想法**：基于人格 + 驱动力 + 上下文生成自发想法并存为记忆；
2. **搜索**：生成查询 → 网络搜索 → 把知识沉淀成记忆；
3. **技能**：在好奇心触发下"习得"新能力；
4. **反思**：对近期记忆做内省。

带**注意力机制**（话题聚焦、来源、强度、衰减）与**内在驱动力**（好奇、内省、玩心），并有冷却防止重复。所有产物写入与用户对话相同的会话，形成统一历史。

### 5.4 桌面感知 Agent
- `agents/chat`：接收 robot_id、消息、当前应用/窗口/屏幕描述/剪贴板，召回相关记忆，以函数调用模式执行（如 `open_browser`、`notify`）。
- `agents/react`：观察桌面活动 → 生成中/日文反应 + 情绪分类（Normal/Happy/Sad/Surprised）+ 可选动作，后台把观察存为记忆。
- 桌面端截屏由内置 **NomiScreenshot.app**（ScreenCaptureKit，独立 TCC 身份）完成，配合 `ocr.swift`（Vision 框架，免权限）做 OCR；二者作为 `extraResources` 打包到 `Contents/Resources/tools/`，代码按 `app.isPackaged` 解析路径。

### 5.5 TTS 管线
- `speak-genie` 按角色配置路由引擎。**CosyVoice2**（:9001）做音色克隆，返回 float32 WAV，经 ffmpeg 转 PCM16 供浏览器播放。
- 文本预处理会清理 markdown、CJK 引号、@提及，并为俏皮音色注入语气词。
- 详细的引擎选型对比（CosyVoice2 / GPT-SoVITS / Qwen3 / edge-tts 等在 Apple Silicon 上的实测）见项目内记忆与 `tts_*` 代码注释。

### 5.6 Live2D 与立绘
桌面渲染层用 pixi-live2d-display 加载 Live2D 模型并做口型同步；无模型时回退到七状态静态立绘。
> ⚠️ 仓库**不包含** Live2D 模型（`desktop/src/renderer/public/live2d/`，受版权保护且体积大），请自行准备并放入该目录。

---

## 6. LLM 集成

通过 `app/services/llm/factory.py` 按 `NOMI_LLM_PROVIDER` 路由：

| 提供方 | 用途 |
|--------|------|
| Claude CLI | 默认，子进程调用 `claude -p` |
| Anthropic API | 设置 `NOMI_ANTHROPIC_API_KEY` 时 |
| OpenAI API | 设置 `NOMI_OPENAI_API_KEY` 时 |
| DeepSeek | 快速聊天模型（`NOMI_DEEPSEEK_API_KEY`） |
| Ollama | 本地 LLM + 向量嵌入（`nomic-embed-text`、视觉用 `minicpm-v`） |
| Gemini | 从图片生成角色 / 视觉任务 |

人格 prompt 在 `app/prompts/` 中构建，强调自然口语（不带 markdown/动作描写）、记忆一致性与关系感知；`robots.system_prompt` 字段允许逐角色覆盖。

---

## 7. 部署

**云端**：PostgreSQL（需 pgvector 扩展）+ 可选 Redis；LLM 用 Claude CLI 或 API key。Web 前端经 Cloudflare tunnel 暴露域名，`/api/*` 反代到后端 `:8100`。

**桌面单机**：SQLite 单文件库；可选本地 Ollama / Whisper / CosyVoice2；运行于 `127.0.0.1:18900`。桌面 App 通过 `electron-builder` 打包为独立 `.app`，自带 Electron + Node 运行时，不依赖系统 PATH。

外部服务（CosyVoice、Ollama、Whisper）未启动时对应功能优雅降级。

---

## 8. 环境变量

见 [`backend/.env.example`](../backend/.env.example)。所有变量以 `NOMI_` 为前缀，放在仓库根目录 `.env`（已 gitignore）。**密钥一律从环境变量读取，不得写入源码。**
