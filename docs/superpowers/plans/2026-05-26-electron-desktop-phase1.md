# Nomi Electron 桌面陪伴器 Phase 1 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a minimal working macOS desktop companion — Electron transparent floating window with avatar, system tray, text chat via bubbles, connected to the Python backend (already adapted for SQLite).

**Architecture:** Electron main process manages a transparent BrowserWindow and spawns the Python backend as a child process. Renderer is a React + Vite app showing the avatar with CSS animations and chat bubbles. Communication with backend over localhost HTTP.

**Tech Stack:** Electron 35, React 19, Vite 6, TypeScript, Tailwind CSS 4

---

## File Structure

```
desktop/
  package.json                       # CREATE: Electron + React + Vite deps
  tsconfig.json                      # CREATE: TypeScript config
  vite.config.ts                     # CREATE: Vite config for renderer
  electron-builder.yml               # CREATE: electron-builder packaging config
  src/
    main/
      index.ts                       # CREATE: Electron main process entry
      backend.ts                     # CREATE: Python backend process manager
      tray.ts                        # CREATE: macOS tray icon + menu
      ipc.ts                         # CREATE: IPC handlers for renderer ↔ main
    preload/
      index.ts                       # CREATE: Preload script (contextBridge)
    renderer/
      index.html                     # CREATE: HTML entry
      main.tsx                       # CREATE: React entry point
      App.tsx                        # CREATE: Root component with state management
      api.ts                         # CREATE: Backend HTTP client (adapted from frontend/src/lib/api.ts)
      types.ts                       # CREATE: Type definitions (copied from frontend/src/lib/types.ts)
      components/
        Avatar.tsx                   # CREATE: Character avatar with CSS idle animations
        Avatar.module.css            # CREATE: Keyframe animations (breathing, blink, states)
        ChatBubble.tsx               # CREATE: Single chat bubble with typewriter effect
        ChatPanel.tsx                # CREATE: Chat area with bubbles + input
        LoadingScreen.tsx            # CREATE: "Waiting for backend" screen
      styles/
        global.css                   # CREATE: Tailwind + base styles
```

---

## Task 1: Electron project scaffold

**Files:**
- Create: `desktop/package.json`
- Create: `desktop/tsconfig.json`
- Create: `desktop/vite.config.ts`
- Create: `desktop/src/renderer/index.html`
- Create: `desktop/src/renderer/styles/global.css`

- [ ] **Step 1: Create package.json**

```json
{
  "name": "nomi-desktop",
  "version": "0.1.0",
  "private": true,
  "main": "dist/main/index.js",
  "scripts": {
    "dev": "concurrently \"vite\" \"tsc -p tsconfig.main.json --watch\" \"electron .\"",
    "build:renderer": "vite build",
    "build:main": "tsc -p tsconfig.main.json",
    "build": "npm run build:renderer && npm run build:main",
    "start": "electron .",
    "pack": "electron-builder --mac"
  },
  "dependencies": {
    "react": "^19.0.0",
    "react-dom": "^19.0.0"
  },
  "devDependencies": {
    "@types/react": "^19",
    "@types/react-dom": "^19",
    "@vitejs/plugin-react": "^4.5.0",
    "concurrently": "^9.1.0",
    "electron": "^35.0.0",
    "electron-builder": "^26.0.0",
    "tailwindcss": "^4",
    "@tailwindcss/vite": "^4",
    "typescript": "^5.8.0",
    "vite": "^6.3.0"
  }
}
```

- [ ] **Step 2: Create tsconfig.json (renderer)**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "outDir": "dist/renderer",
    "rootDir": "src/renderer",
    "baseUrl": "src/renderer",
    "paths": {
      "@/*": ["./*"]
    }
  },
  "include": ["src/renderer"]
}
```

Create `desktop/tsconfig.main.json` (main process):

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "commonjs",
    "moduleResolution": "node",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "outDir": "dist/main",
    "rootDir": "src/main"
  },
  "include": ["src/main", "src/preload"]
}
```

- [ ] **Step 3: Create vite.config.ts**

```typescript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  root: "src/renderer",
  base: "./",
  build: {
    outDir: "../../dist/renderer",
    emptyOutDir: true,
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src/renderer"),
    },
  },
  server: {
    port: 5173,
  },
});
```

- [ ] **Step 4: Create index.html**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Nomi</title>
  <style>
    /* Transparent background for floating window */
    html, body, #root {
      margin: 0;
      padding: 0;
      background: transparent;
      overflow: hidden;
    }
  </style>
</head>
<body>
  <div id="root"></div>
  <script type="module" src="./main.tsx"></script>
</body>
</html>
```

- [ ] **Step 5: Create global.css**

```css
@import "tailwindcss";

* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: transparent;
  -webkit-app-region: no-drag;
  user-select: none;
}
```

- [ ] **Step 6: Install dependencies**

```bash
cd /Users/chao/Documents/Projects/nomi/desktop && npm install
```

- [ ] **Step 7: Commit**

```bash
git add desktop/package.json desktop/package-lock.json desktop/tsconfig.json desktop/tsconfig.main.json desktop/vite.config.ts desktop/src/renderer/index.html desktop/src/renderer/styles/global.css
git commit -m "feat(desktop): scaffold Electron + React + Vite project"
```

---

## Task 2: Electron main process + transparent window

**Files:**
- Create: `desktop/src/main/index.ts`
- Create: `desktop/src/preload/index.ts`

- [ ] **Step 1: Create preload script**

Create `desktop/src/preload/index.ts`:

```typescript
import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("nomi", {
  toggleExpand: () => ipcRenderer.invoke("toggle-expand"),
  minimize: () => ipcRenderer.invoke("minimize-to-tray"),
  getBackendStatus: () => ipcRenderer.invoke("get-backend-status"),
  onBackendReady: (callback: () => void) => {
    ipcRenderer.on("backend-ready", callback);
    return () => ipcRenderer.removeListener("backend-ready", callback);
  },
});
```

- [ ] **Step 2: Create main process entry**

Create `desktop/src/main/index.ts`:

```typescript
import { app, BrowserWindow, globalShortcut } from "electron";
import path from "path";
import { setupTray } from "./tray";
import { startBackend, stopBackend, isBackendReady } from "./backend";
import { setupIPC } from "./ipc";

let mainWindow: BrowserWindow | null = null;
let isExpanded = false;

const COMPACT_SIZE = { width: 220, height: 320 };
const EXPANDED_SIZE = { width: 420, height: 620 };

function createWindow() {
  mainWindow = new BrowserWindow({
    width: COMPACT_SIZE.width,
    height: COMPACT_SIZE.height,
    transparent: true,
    frame: false,
    alwaysOnTop: true,
    resizable: false,
    hasShadow: false,
    skipTaskbar: true,
    webPreferences: {
      preload: path.join(__dirname, "..", "preload", "index.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  // Position at bottom-right of screen
  const { screen } = require("electron");
  const display = screen.getPrimaryDisplay();
  const { width, height } = display.workAreaSize;
  mainWindow.setPosition(
    width - COMPACT_SIZE.width - 20,
    height - COMPACT_SIZE.height - 20
  );

  if (process.env.NODE_ENV === "development") {
    mainWindow.loadURL("http://localhost:5173");
  } else {
    mainWindow.loadFile(path.join(__dirname, "..", "renderer", "index.html"));
  }

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

export function toggleExpand() {
  if (!mainWindow) return;
  isExpanded = !isExpanded;
  const size = isExpanded ? EXPANDED_SIZE : COMPACT_SIZE;
  mainWindow.setSize(size.width, size.height, true);
}

export function showWindow() {
  mainWindow?.show();
}

export function hideWindow() {
  mainWindow?.hide();
}

export function getMainWindow() {
  return mainWindow;
}

app.whenReady().then(async () => {
  createWindow();
  setupIPC();
  setupTray();

  // Global shortcut: Cmd+Shift+N to toggle visibility
  globalShortcut.register("CommandOrControl+Shift+N", () => {
    if (mainWindow?.isVisible()) {
      hideWindow();
    } else {
      showWindow();
    }
  });

  // Start Python backend
  startBackend();
});

app.on("will-quit", () => {
  globalShortcut.unregisterAll();
  stopBackend();
});

// macOS: keep app running when window is closed
app.on("window-all-closed", (e: Event) => {
  e.preventDefault();
});
```

- [ ] **Step 3: Verify it compiles**

```bash
cd /Users/chao/Documents/Projects/nomi/desktop && npx tsc -p tsconfig.main.json --noEmit
```

Expected: No errors (backend.ts and tray.ts don't exist yet, so this will fail — that's expected, we create them in next tasks)

- [ ] **Step 4: Commit**

```bash
git add desktop/src/main/index.ts desktop/src/preload/index.ts
git commit -m "feat(desktop): Electron main process with transparent floating window"
```

---

## Task 3: Python backend process manager

**Files:**
- Create: `desktop/src/main/backend.ts`

- [ ] **Step 1: Create backend.ts**

```typescript
import { ChildProcess, spawn } from "child_process";
import path from "path";
import { app } from "electron";
import { getMainWindow } from "./index";

let backendProcess: ChildProcess | null = null;
let backendReady = false;
const BACKEND_PORT = 18900;
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;

export function getBackendUrl(): string {
  return BACKEND_URL;
}

export function isBackendReady(): boolean {
  return backendReady;
}

function getServerPath(): string {
  if (process.env.NODE_ENV === "development") {
    // In dev: use the PyInstaller-built binary or run directly
    return path.join(
      app.getAppPath(),
      "..",
      "backend",
      "desktop",
      "dist",
      "nomi-server"
    );
  }
  // In production: bundled inside app resources
  return path.join(process.resourcesPath, "backend", "nomi-server");
}

export function startBackend(): void {
  const serverPath = getServerPath();
  console.log(`[backend] Starting: ${serverPath}`);

  try {
    backendProcess = spawn(serverPath, [], {
      stdio: ["ignore", "pipe", "pipe"],
      env: { ...process.env },
    });

    backendProcess.stdout?.on("data", (data: Buffer) => {
      console.log(`[backend] ${data.toString().trim()}`);
    });

    backendProcess.stderr?.on("data", (data: Buffer) => {
      console.error(`[backend] ${data.toString().trim()}`);
    });

    backendProcess.on("exit", (code: number | null) => {
      console.log(`[backend] Exited with code ${code}`);
      backendReady = false;
      backendProcess = null;
    });

    // Start health checking
    pollBackendHealth();
  } catch (err) {
    console.error(`[backend] Failed to start: ${err}`);
  }
}

export function stopBackend(): void {
  if (backendProcess && !backendProcess.killed) {
    console.log("[backend] Stopping...");
    backendProcess.kill("SIGTERM");
    // Force kill after 3 seconds
    setTimeout(() => {
      if (backendProcess && !backendProcess.killed) {
        backendProcess.kill("SIGKILL");
      }
    }, 3000);
  }
}

async function pollBackendHealth(): Promise<void> {
  const maxAttempts = 30; // 15 seconds
  for (let i = 0; i < maxAttempts; i++) {
    try {
      const response = await fetch(`${BACKEND_URL}/api/status`);
      if (response.ok) {
        console.log("[backend] Ready!");
        backendReady = true;
        getMainWindow()?.webContents.send("backend-ready");
        return;
      }
    } catch {
      // Not ready yet
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  console.error("[backend] Failed to become ready after 15 seconds");
}
```

- [ ] **Step 2: Commit**

```bash
git add desktop/src/main/backend.ts
git commit -m "feat(desktop): Python backend process manager with health polling"
```

---

## Task 4: Tray icon + IPC handlers

**Files:**
- Create: `desktop/src/main/tray.ts`
- Create: `desktop/src/main/ipc.ts`

- [ ] **Step 1: Create tray.ts**

```typescript
import { Tray, Menu, nativeImage, app } from "electron";
import path from "path";
import { showWindow, hideWindow, getMainWindow } from "./index";

let tray: Tray | null = null;

export function setupTray(): void {
  // Use a simple template image for macOS menu bar
  const iconPath = path.join(app.getAppPath(), "assets", "tray-icon.png");
  let icon: nativeImage;
  try {
    icon = nativeImage.createFromPath(iconPath);
    icon = icon.resize({ width: 18, height: 18 });
    icon.setTemplateImage(true);
  } catch {
    // Fallback: create a simple icon programmatically
    icon = nativeImage.createEmpty();
  }

  tray = new Tray(icon);
  tray.setToolTip("Nomi Companion");

  const contextMenu = Menu.buildFromTemplate([
    {
      label: "显示/隐藏角色",
      click: () => {
        const win = getMainWindow();
        if (win?.isVisible()) {
          hideWindow();
        } else {
          showWindow();
        }
      },
    },
    { type: "separator" },
    {
      label: "退出 Nomi",
      click: () => {
        app.quit();
      },
    },
  ]);

  tray.setContextMenu(contextMenu);

  // Click tray icon to toggle window
  tray.on("click", () => {
    const win = getMainWindow();
    if (win?.isVisible()) {
      hideWindow();
    } else {
      showWindow();
    }
  });
}
```

- [ ] **Step 2: Create ipc.ts**

```typescript
import { ipcMain } from "electron";
import { toggleExpand } from "./index";
import { isBackendReady } from "./backend";

export function setupIPC(): void {
  ipcMain.handle("toggle-expand", () => {
    toggleExpand();
  });

  ipcMain.handle("minimize-to-tray", () => {
    const { getMainWindow } = require("./index");
    getMainWindow()?.hide();
  });

  ipcMain.handle("get-backend-status", () => {
    return isBackendReady();
  });
}
```

- [ ] **Step 3: Create tray icon asset directory**

```bash
mkdir -p /Users/chao/Documents/Projects/nomi/desktop/assets
```

Create a placeholder tray icon (a simple 36x36 PNG). For now, the app will use `nativeImage.createEmpty()` as fallback.

- [ ] **Step 4: Verify main process compiles**

```bash
cd /Users/chao/Documents/Projects/nomi/desktop && npx tsc -p tsconfig.main.json --noEmit
```

Expected: PASS (all main process files now exist)

- [ ] **Step 5: Commit**

```bash
git add desktop/src/main/tray.ts desktop/src/main/ipc.ts desktop/assets/
git commit -m "feat(desktop): tray icon with show/hide menu, IPC handlers"
```

---

## Task 5: React entry + types + API client

**Files:**
- Create: `desktop/src/renderer/main.tsx`
- Create: `desktop/src/renderer/types.ts`
- Create: `desktop/src/renderer/api.ts`

- [ ] **Step 1: Create types.ts**

Copy and adapt from `frontend/src/lib/types.ts`:

```typescript
export interface Robot {
  id: string;
  name: string;
  age: number | null;
  current_emotion: { emotion: string; intensity: number } | null;
  current_status: string | null;
}

export interface ChatMessage {
  id: string;
  sender_type: string | null;
  sender_id: string | null;
  sender_name: string | null;
  content: string | null;
  emotion: Record<string, unknown> | null;
  created_at: string;
}

export interface Conversation {
  id: string;
  messages: ChatMessage[];
}
```

- [ ] **Step 2: Create api.ts**

```typescript
const BACKEND_URL = "http://127.0.0.1:18900";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BACKEND_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export const api = {
  listRobots: () => request<import("./types").Robot[]>("/api/robots"),

  createConversation: () =>
    request<{ id: string }>("/api/conversations", { method: "POST" }),

  sendMessage: (conversationId: string, content: string, model: string, robotId?: string) => {
    let url = `/api/conversations/${conversationId}/message?model=${model}`;
    if (robotId) url += `&robot_id=${robotId}`;
    return request<{ messages: import("./types").ChatMessage[] }>(url, {
      method: "POST",
      body: JSON.stringify({ content }),
    });
  },

  getLatestConversation: () =>
    request<import("./types").Conversation | null>("/api/conversations/latest"),

  getStatus: () => request<{ status: string }>("/api/status"),
};
```

- [ ] **Step 3: Create main.tsx**

```tsx
import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles/global.css";

const root = createRoot(document.getElementById("root")!);
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
```

- [ ] **Step 4: Commit**

```bash
git add desktop/src/renderer/main.tsx desktop/src/renderer/types.ts desktop/src/renderer/api.ts
git commit -m "feat(desktop): React entry, API client, and type definitions"
```

---

## Task 6: Avatar component with CSS animations

**Files:**
- Create: `desktop/src/renderer/components/Avatar.tsx`
- Create: `desktop/src/renderer/components/Avatar.module.css`

- [ ] **Step 1: Create Avatar.module.css**

```css
.avatar {
  position: relative;
  width: 160px;
  height: 160px;
  cursor: pointer;
  -webkit-app-region: drag;
}

.avatarImage {
  width: 100%;
  height: 100%;
  border-radius: 50%;
  object-fit: cover;
}

/* Breathing animation - always active in idle */
.idle .avatarImage {
  animation: breathe 3s ease-in-out infinite, bob 4s ease-in-out infinite;
}

@keyframes breathe {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.03); }
}

@keyframes bob {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-4px); }
}

/* Combined breathing + bobbing */
.idle .avatarImage {
  animation: idleMove 4s ease-in-out infinite;
}

@keyframes idleMove {
  0%, 100% {
    transform: scale(1) translateY(0);
  }
  25% {
    transform: scale(1.02) translateY(-2px);
  }
  50% {
    transform: scale(1.03) translateY(-4px);
  }
  75% {
    transform: scale(1.02) translateY(-2px);
  }
}

/* Blink overlay */
.blinkOverlay {
  position: absolute;
  top: 35%;
  left: 15%;
  width: 70%;
  height: 12%;
  background: var(--blink-color, #f5e6d3);
  border-radius: 50%;
  opacity: 0;
  pointer-events: none;
}

.blinking .blinkOverlay {
  animation: blink 0.15s ease-in-out;
}

@keyframes blink {
  0%, 100% { opacity: 0; }
  50% { opacity: 0.9; }
}

/* Thinking state */
.thinking .avatarImage {
  animation: think 2s ease-in-out infinite;
}

@keyframes think {
  0%, 100% { transform: rotate(0deg) scale(1); }
  50% { transform: rotate(3deg) scale(1.01); }
}

/* Speaking state */
.speaking .avatarImage {
  animation: speak 0.3s ease-in-out infinite alternate;
}

@keyframes speak {
  0% { transform: scale(1); }
  100% { transform: scale(1.02); }
}

/* Listening state */
.listening .avatarImage {
  animation: listen 1.5s ease-in-out infinite;
}

@keyframes listen {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.05); }
}

/* Status indicator dot */
.statusDot {
  position: absolute;
  bottom: 8px;
  right: 8px;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: 2px solid rgba(255, 255, 255, 0.8);
}

.statusDot.ready {
  background: #4ade80;
}

.statusDot.thinking {
  background: #facc15;
  animation: pulse 1s ease-in-out infinite;
}

.statusDot.speaking {
  background: #60a5fa;
  animation: pulse 0.5s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}
```

- [ ] **Step 2: Create Avatar.tsx**

```tsx
import { useEffect, useRef, useState } from "react";
import styles from "./Avatar.module.css";

export type CharacterState = "idle" | "listening" | "thinking" | "speaking";

interface AvatarProps {
  avatarUrl?: string;
  state: CharacterState;
  onClick: () => void;
}

export function Avatar({ avatarUrl, state, onClick }: AvatarProps) {
  const [isBlinking, setIsBlinking] = useState(false);
  const blinkTimer = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    function scheduleBlink() {
      const delay = 3000 + Math.random() * 3000; // 3-6 seconds
      blinkTimer.current = setTimeout(() => {
        setIsBlinking(true);
        setTimeout(() => {
          setIsBlinking(false);
          scheduleBlink();
        }, 150);
      }, delay);
    }
    scheduleBlink();
    return () => clearTimeout(blinkTimer.current);
  }, []);

  const stateClass = styles[state] || styles.idle;
  const blinkClass = isBlinking ? styles.blinking : "";

  return (
    <div
      className={`${styles.avatar} ${stateClass} ${blinkClass}`}
      onClick={onClick}
    >
      <img
        className={styles.avatarImage}
        src={avatarUrl || "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><circle cx='50' cy='50' r='45' fill='%23e8d5c4'/><circle cx='35' cy='42' r='5' fill='%23333'/><circle cx='65' cy='42' r='5' fill='%23333'/><path d='M 35 62 Q 50 72 65 62' stroke='%23333' stroke-width='2' fill='none'/></svg>"}
        alt="Nomi"
        draggable={false}
      />
      <div className={styles.blinkOverlay} />
      <div
        className={`${styles.statusDot} ${
          state === "thinking"
            ? styles.thinking
            : state === "speaking"
            ? styles.speaking
            : styles.ready
        }`}
      />
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add desktop/src/renderer/components/Avatar.tsx desktop/src/renderer/components/Avatar.module.css
git commit -m "feat(desktop): avatar component with CSS idle/thinking/speaking animations"
```

---

## Task 7: Chat bubble + chat panel

**Files:**
- Create: `desktop/src/renderer/components/ChatBubble.tsx`
- Create: `desktop/src/renderer/components/ChatPanel.tsx`

- [ ] **Step 1: Create ChatBubble.tsx**

```tsx
import { useEffect, useState } from "react";

interface ChatBubbleProps {
  text: string;
  isUser: boolean;
  typewriter?: boolean;
  onTypingDone?: () => void;
}

export function ChatBubble({ text, isUser, typewriter = false, onTypingDone }: ChatBubbleProps) {
  const [displayText, setDisplayText] = useState(typewriter ? "" : text);
  const [fading, setFading] = useState(false);

  useEffect(() => {
    if (!typewriter) return;

    let index = 0;
    const timer = setInterval(() => {
      index++;
      setDisplayText(text.slice(0, index));
      if (index >= text.length) {
        clearInterval(timer);
        onTypingDone?.();
      }
    }, 33); // ~30 chars/sec

    return () => clearInterval(timer);
  }, [text, typewriter, onTypingDone]);

  return (
    <div
      className={`
        max-w-[280px] px-3 py-2 rounded-2xl text-sm leading-relaxed
        transition-opacity duration-500
        ${fading ? "opacity-0" : "opacity-100"}
        ${isUser
          ? "bg-blue-100 text-gray-800 self-end rounded-br-sm"
          : "bg-white text-gray-800 self-start rounded-bl-sm shadow-sm"
        }
      `}
    >
      {displayText}
      {typewriter && displayText.length < text.length && (
        <span className="animate-pulse">▊</span>
      )}
    </div>
  );
}

export function fadeOut(ref: HTMLDivElement) {
  ref.style.transition = "opacity 0.5s";
  ref.style.opacity = "0";
}
```

- [ ] **Step 2: Create ChatPanel.tsx**

```tsx
import { useRef, useState } from "react";
import { ChatBubble } from "./ChatBubble";
import type { ChatMessage } from "../types";

interface ChatPanelProps {
  messages: ChatMessage[];
  onSend: (text: string) => void;
  isWaiting: boolean;
}

export function ChatPanel({ messages, onSend, isWaiting }: ChatPanelProps) {
  const [input, setInput] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  // Only show last 4 messages
  const visibleMessages = messages.slice(-4);

  function handleSend() {
    const text = input.trim();
    if (!text || isWaiting) return;
    setInput("");
    onSend(text);
    inputRef.current?.focus();
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Messages area */}
      <div className="flex-1 flex flex-col gap-2 px-3 py-2 overflow-hidden justify-end">
        {visibleMessages.map((msg, i) => (
          <ChatBubble
            key={msg.id}
            text={msg.content || ""}
            isUser={msg.sender_type === "user"}
            typewriter={
              msg.sender_type !== "user" && i === visibleMessages.length - 1
            }
          />
        ))}
        {isWaiting && (
          <div className="self-start px-3 py-2 bg-white rounded-2xl rounded-bl-sm shadow-sm text-sm text-gray-400">
            <span className="animate-pulse">思考中...</span>
          </div>
        )}
      </div>

      {/* Input area */}
      <div className="flex items-center gap-2 px-3 py-2 border-t border-gray-100">
        <input
          ref={inputRef}
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="说点什么..."
          disabled={isWaiting}
          className="flex-1 px-3 py-2 text-sm rounded-full bg-gray-50 border border-gray-200 outline-none focus:border-blue-300 disabled:opacity-50"
        />
        <button
          onClick={handleSend}
          disabled={isWaiting || !input.trim()}
          className="px-3 py-2 text-sm rounded-full bg-blue-500 text-white disabled:opacity-30 hover:bg-blue-600 transition-colors"
        >
          发送
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add desktop/src/renderer/components/ChatBubble.tsx desktop/src/renderer/components/ChatPanel.tsx
git commit -m "feat(desktop): chat bubble with typewriter effect and chat panel"
```

---

## Task 8: Loading screen + App root component

**Files:**
- Create: `desktop/src/renderer/components/LoadingScreen.tsx`
- Create: `desktop/src/renderer/App.tsx`

- [ ] **Step 1: Create LoadingScreen.tsx**

```tsx
export function LoadingScreen() {
  return (
    <div className="flex flex-col items-center justify-center h-screen bg-transparent">
      <div className="w-12 h-12 rounded-full bg-gradient-to-br from-amber-200 to-rose-200 animate-pulse" />
      <p className="mt-3 text-xs text-gray-400">正在启动...</p>
    </div>
  );
}
```

- [ ] **Step 2: Create App.tsx**

```tsx
import { useCallback, useEffect, useState } from "react";
import { Avatar, type CharacterState } from "./components/Avatar";
import { ChatPanel } from "./components/ChatPanel";
import { LoadingScreen } from "./components/LoadingScreen";
import { api } from "./api";
import type { ChatMessage, Robot } from "./types";

declare global {
  interface Window {
    nomi: {
      toggleExpand: () => void;
      minimize: () => void;
      getBackendStatus: () => Promise<boolean>;
      onBackendReady: (callback: () => void) => () => void;
    };
  }
}

export default function App() {
  const [backendReady, setBackendReady] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [robot, setRobot] = useState<Robot | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [characterState, setCharacterState] = useState<CharacterState>("idle");
  const [isWaiting, setIsWaiting] = useState(false);

  // Listen for backend ready signal
  useEffect(() => {
    // Check if already ready
    window.nomi.getBackendStatus().then((ready) => {
      if (ready) setBackendReady(true);
    });

    const cleanup = window.nomi.onBackendReady(() => {
      setBackendReady(true);
    });
    return cleanup;
  }, []);

  // Load robot when backend is ready
  useEffect(() => {
    if (!backendReady) return;

    api.listRobots().then((robots) => {
      if (robots.length > 0) {
        setRobot(robots[0]);
      }
    });

    // Load latest conversation
    api.getLatestConversation().then((conv) => {
      if (conv) {
        setConversationId(conv.id);
        setMessages(conv.messages);
      }
    });
  }, [backendReady]);

  const handleAvatarClick = useCallback(() => {
    setExpanded((prev) => !prev);
    window.nomi.toggleExpand();
  }, []);

  const handleSend = useCallback(
    async (text: string) => {
      if (!robot) return;

      setIsWaiting(true);
      setCharacterState("thinking");

      try {
        let convId = conversationId;
        if (!convId) {
          const conv = await api.createConversation();
          convId = conv.id;
          setConversationId(convId);
        }

        const result = await api.sendMessage(
          convId,
          text,
          "deepseek-v4-flash",
          robot.id
        );

        setMessages((prev) => [...prev, ...result.messages]);
        setCharacterState("speaking");

        // Return to idle after "speaking" for a bit
        setTimeout(() => setCharacterState("idle"), 2000);
      } catch (err) {
        console.error("Send failed:", err);
        setCharacterState("idle");
      } finally {
        setIsWaiting(false);
      }
    },
    [robot, conversationId]
  );

  if (!backendReady) {
    return <LoadingScreen />;
  }

  return (
    <div className="flex flex-col items-center h-screen bg-transparent">
      {/* Avatar - always visible */}
      <div className="flex-shrink-0 pt-4">
        <Avatar
          avatarUrl={undefined} // Will use default SVG face
          state={characterState}
          onClick={handleAvatarClick}
        />
        {robot && (
          <p className="text-center text-xs text-gray-500 mt-1">{robot.name}</p>
        )}
      </div>

      {/* Chat panel - visible when expanded */}
      {expanded && (
        <div className="flex-1 w-full bg-white/80 backdrop-blur-sm rounded-t-2xl mt-2 overflow-hidden">
          <ChatPanel
            messages={messages}
            onSend={handleSend}
            isWaiting={isWaiting}
          />
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add desktop/src/renderer/components/LoadingScreen.tsx desktop/src/renderer/App.tsx
git commit -m "feat(desktop): App root with avatar, chat panel, backend lifecycle"
```

---

## Task 9: Electron-builder config + dev workflow

**Files:**
- Create: `desktop/electron-builder.yml`
- Modify: `desktop/package.json` (add dev scripts if needed)

- [ ] **Step 1: Create electron-builder.yml**

```yaml
appId: com.nomi.desktop
productName: Nomi
directories:
  output: release
mac:
  target:
    - target: dmg
      arch: arm64
  category: public.app-category.social-networking
  icon: assets/icon.icns
  darkModeSupport: true
  extendInfo:
    NSMicrophoneUsageDescription: "Nomi needs microphone access for voice conversations"
files:
  - dist/**/*
  - assets/**/*
extraResources:
  - from: ../backend/desktop/dist/nomi-server
    to: backend/nomi-server
dmg:
  contents:
    - x: 130
      y: 220
    - x: 410
      y: 220
      type: link
      path: /Applications
```

- [ ] **Step 2: Add .gitignore for desktop**

Create `desktop/.gitignore`:

```
node_modules/
dist/
release/
*.js
*.js.map
*.d.ts
!vite.config.ts
!src/**/*.ts
!src/**/*.tsx
```

- [ ] **Step 3: Verify full build pipeline**

```bash
cd /Users/chao/Documents/Projects/nomi/desktop
npm run build:renderer
npm run build:main
```

Expected: Both pass, `dist/` directory created with compiled files.

- [ ] **Step 4: Test dev mode**

```bash
cd /Users/chao/Documents/Projects/nomi/desktop
# Start just the Vite dev server to verify renderer works
npx vite --config vite.config.ts
```

Open `http://localhost:5173` — should show the loading screen (backend not running).

- [ ] **Step 5: Commit**

```bash
git add desktop/electron-builder.yml desktop/.gitignore
git commit -m "feat(desktop): electron-builder config and dev workflow"
```

---

## Task 10: Integration test — full app launch

**Context:** Wire everything together and test the complete flow: Electron → backend → avatar → chat.

- [ ] **Step 1: Ensure backend is built**

```bash
cd /Users/chao/Documents/Projects/nomi/backend
python desktop/build.py
```

(This builds `backend/desktop/dist/nomi-server`)

- [ ] **Step 2: Build and launch Electron app**

```bash
cd /Users/chao/Documents/Projects/nomi/desktop
npm run build
npm start
```

- [ ] **Step 3: Verify the following manually**

1. App window appears (transparent, floating, always on top)
2. Loading screen shows "正在启动..."
3. Backend starts (check terminal logs for `[backend] Ready!`)
4. Avatar appears with breathing/bobbing animation
5. Tray icon appears in macOS menu bar
6. Click avatar → window expands with chat panel
7. Type a message → bot responds → bubble appears with typewriter effect
8. Avatar changes to thinking → speaking → idle states
9. `⌘+Shift+N` toggles window visibility
10. Tray icon click toggles window visibility

- [ ] **Step 4: Fix any issues found**

If issues are found, fix and re-test.

- [ ] **Step 5: Final commit**

```bash
git add -A desktop/
git commit -m "feat(desktop): Phase 1 complete — Electron desktop companion with chat"
```
