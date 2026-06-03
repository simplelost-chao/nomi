# Nomi 桌面陪伴器设计文档

## 概述

将 Nomi 从 Web 应用转变为 macOS 桌面陪伴应用。角色作为桌面常驻伙伴，通过语音和文字与用户互动。

**技术栈：** Electron (React + Vite) 客户端 + 打包的 Python 后端（FastAPI + SQLite）

**核心体验：** 角色常驻桌面，有待机动画，用户可以随时语音/文字对话，角色有表情和动画反馈。

---

## 1. 整体架构

```
┌──────────────────────────────────────┐
│          Electron App                │
│  ┌────────────────────────────────┐  │
│  │  Main Process (Node.js)       │  │
│  │  - 窗口管理（悬浮/展开/托盘） │  │
│  │  - Python 后端子进程管理      │  │
│  │  - 全局快捷键                 │  │
│  └──────────┬─────────────────────┘  │
│             │ IPC                     │
│  ┌──────────▼─────────────────────┐  │
│  │  Renderer Process (Web)       │  │
│  │  - 角色头像 + CSS/Lottie 动画 │  │
│  │  - 聊天气泡 UI               │  │
│  │  - 语音控制                   │  │
│  └────────────────────────────────┘  │
│             │ HTTP/WS                │
│  ┌──────────▼─────────────────────┐  │
│  │  Python Backend (子进程)      │  │
│  │  FastAPI + SQLite + 内存缓存  │  │
│  │  LLM · TTS · STT · 记忆系统  │  │
│  └────────────────────────────────┘  │
└──────────────────────────────────────┘
```

### 通信方式

- Main Process 管理 Python 后端子进程
- Renderer 通过 `localhost:18900` HTTP/WebSocket 与 Python 后端通信
- Main ↔ Renderer 通过 Electron IPC 通信（窗口控制、托盘事件）

### 与 Web 版的关系

- Next.js 前端不再使用，Electron + React + Vite 替代
- Next.js API 路由不再使用，直接调 Python 后端
- 部分前端逻辑可复用（API 调用、类型定义）
- Python 后端核心逻辑全部复用

---

## 2. Electron 客户端

### 2.1 窗口模式

三种状态可切换：

| 模式 | Electron 实现 |
|------|---------------|
| **悬浮头像** | `BrowserWindow({ transparent: true, frame: false, alwaysOnTop: true, width: 200, height: 300 })`，可拖拽 |
| **对话模式** | 点击头像后同一窗口 resize 展开（约 400x600），显示气泡区域 + 输入框 |
| **托盘模式** | `Tray` API，菜单栏图标，窗口 `hide()`，点击 `show()` |

### 2.2 角色动画

使用 CSS 动画 + 分层 PNG 实现：

角色头像拆分为图层（头/身体、眼睛、嘴巴），每层独立 CSS 动画控制。

**状态机：**

```
        ┌──────────┐
        │   待机   │ ← CSS: scale 呼吸 + translateY 微浮
        └────┬─────┘
             │ 用户点击/说话
        ┌────▼─────┐
        │   倾听   │ ← CSS: 眼睛放大 + 轻微前倾
        └────┬─────┘
             │ 收到回复
        ┌────▼─────┐
        │   思考   │ ← CSS: rotate 歪头 + 省略号气泡
        └────┬─────┘
             │ TTS 开始
        ┌────▼─────┐
        │   说话   │ ← CSS: 嘴部快速 scale + 表情配合情绪
        └────┬─────┘
             │ 播放完毕
             └──→ 待机
```

**眨眼：** 随机间隔（3-6秒），CSS opacity 切换眼睛覆盖层，持续 150ms

**情绪表情：** 根据后端返回的情绪标签切换眼睛/嘴巴图层的 CSS class

### 2.3 对话 UI

- 角色旁气泡，逐字显示文本（打字机效果，CSS `@keyframes` + JS 定时器）
- 只保留最近 2-3 条消息，旧消息 CSS `opacity` 淡出后移除
- 底部麦克风按钮 + 文字输入框
- 用户消息和 Bot 消息用不同颜色气泡

### 2.4 前端技术选择

- **React 19** + **Vite** — 轻量快速，不需要 Next.js 的 SSR
- **CSS Modules** 或 **Tailwind** — 复用现有样式习惯
- **Lottie-web**（可选）— 如果 CSS 动画不够用，可加 Lottie 播放更复杂的动画

---

## 3. Python 后端适配（已完成）

### 3.1 数据库

- PostgreSQL → SQLite（`sqlite+aiosqlite:///`）
- 向量搜索：pgvector → numpy cosine similarity
- JSONB/ARRAY → 便携 JSON/Text 类型

### 3.2 缓存

- Redis → Python 内存缓存（单用户不需要 Redis）

### 3.3 打包

PyInstaller 打包为 macOS 可执行文件 `nomi-server`。

应用 bundle 结构：

```
Nomi.app/
  Contents/
    MacOS/
      Nomi                 ← Electron 主程序
    Resources/
      app.asar             ← Electron 前端资源
      backend/
        nomi-server        ← PyInstaller 打包的 Python 后端
      avatars/             ← 角色素材
```

### 3.4 启动流程

1. Electron main process 拉起 `nomi-server` 子进程
2. 轮询 `GET /api/status` 等待后端就绪
3. 后端就绪后加载 renderer，渲染角色进入待机

### 3.5 API 变更

现有 API 全部保留，新增：

| 接口 | 方法 | 用途 |
|------|------|------|
| `/api/status` | GET | 健康检查（已实现） |
| `/api/chat/stream` | WebSocket | 流式对话 + 情绪标签 |
| `/api/tts/stream` | GET | TTS 音频流式返回 |

情绪标签格式：

```json
{
  "type": "token",
  "content": "你好呀",
  "emotion": "happy",
  "finished": false
}
```

支持的情绪标签：`neutral`、`happy`、`sad`、`thinking`、`surprised`、`angry`

---

## 4. macOS 系统集成

### 4.1 托盘菜单

Electron `Tray` API 实现：

```
┌──────────────────┐
│ 显示/隐藏角色     │
│ 切换角色    ▶     │
│ ──────────────── │
│ 音量调节    ▶     │
│ 麦克风设置  ▶     │
│ ──────────────── │
│ 开机自启动        │
│ 偏好设置...       │
│ 退出 Nomi        │
└──────────────────┘
```

### 4.2 权限

- **麦克风权限** — Electron `systemPreferences.askForMediaAccess('microphone')`

### 4.3 全局快捷键

Electron `globalShortcut` API：

| 快捷键 | 功能 |
|--------|------|
| `⌘ + Shift + N` | 显示/隐藏角色 |
| `Space`（窗口聚焦时） | 按住说话 |

### 4.4 数据存储

```
~/Library/Application Support/Nomi/
  nomi.db              ← SQLite 数据库
  config.json          ← 用户设置
  logs/                ← 后端日志
  tts_cache/           ← TTS 音频缓存
```

---

## 5. 开发分期

### 第一期：最小可用版本

- Electron 透明悬浮窗 + 静态角色头像
- 托盘图标 + 显示/隐藏
- Python 后端子进程管理 + 健康检查
- 点击展开对话气泡 UI + 文字输入
- 文字对话（HTTP 调用现有 API）
- 基本 CSS 待机动画（呼吸/眨眼）

### 第二期：语音 + 动画

- TTS 集成 + Web Audio API 播放
- STT 集成 + 麦克风输入
- 角色动画状态机完善（倾听/思考/说话）
- WebSocket 流式对话
- 情绪标签 → 表情切换

### 第三期：精细打磨

- 分层 PNG 角色 + 独立部件动画
- 多角色切换
- 开机自启动（Electron `app.setLoginItemSettings`）
- 偏好设置面板
- electron-builder 打包 DMG 分发
