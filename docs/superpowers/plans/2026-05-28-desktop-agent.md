# Desktop Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add desktop agent capabilities (screen sensing, clipboard monitoring, app detection, web search, notifications) to the Nomi Electron companion, with local Ollama filtering and cloud LLM character reactions.

**Architecture:** Dual-layer agent — Electron main process runs sensors and local Ollama analysis, backend generates character reactions via cloud LLM. All capabilities individually toggleable via config file and UI settings panel.

**Tech Stack:** Electron (main process TypeScript), Ollama (minicpm-v vision model), FastAPI backend, React renderer

---

### Task 1: Agent Config Module

**Files:**
- Create: `desktop/src/main/agent/agent-config.ts`

- [ ] **Step 1: Create the config module**

```typescript
// desktop/src/main/agent/agent-config.ts
import { app } from "electron";
import fs from "fs";
import path from "path";

export interface AgentConfig {
  screenSensor: { enabled: boolean; intervalSec: number };
  clipboardSensor: { enabled: boolean };
  appSensor: { enabled: boolean };
  webSearch: { enabled: boolean };
  notification: { enabled: boolean };
  fileAccess: { enabled: boolean };
  openUrl: { enabled: boolean };
  voice: { enabled: boolean };
  minReactionIntervalSec: number;
  ollamaModel: string;
  ollamaUrl: string;
}

const DEFAULT_CONFIG: AgentConfig = {
  screenSensor: { enabled: false, intervalSec: 30 },
  clipboardSensor: { enabled: false },
  appSensor: { enabled: false },
  webSearch: { enabled: true },
  notification: { enabled: true },
  fileAccess: { enabled: false },
  openUrl: { enabled: true },
  voice: { enabled: true },
  minReactionIntervalSec: 120,
  ollamaModel: "minicpm-v",
  ollamaUrl: "http://localhost:11434",
};

function getConfigPath(): string {
  const dir = path.join(app.getPath("home"), ".nomi");
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  return path.join(dir, "agent-config.json");
}

export function loadConfig(): AgentConfig {
  const configPath = getConfigPath();
  if (!fs.existsSync(configPath)) {
    saveConfig(DEFAULT_CONFIG);
    return { ...DEFAULT_CONFIG };
  }
  try {
    const raw = fs.readFileSync(configPath, "utf-8");
    return { ...DEFAULT_CONFIG, ...JSON.parse(raw) };
  } catch {
    return { ...DEFAULT_CONFIG };
  }
}

export function saveConfig(config: AgentConfig): void {
  fs.writeFileSync(getConfigPath(), JSON.stringify(config, null, 2));
}

export function updateConfig(partial: Partial<AgentConfig>): AgentConfig {
  const current = loadConfig();
  const merged = { ...current, ...partial };
  saveConfig(merged);
  return merged;
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd desktop && npx tsc -p tsconfig.main.json --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add desktop/src/main/agent/agent-config.ts
git commit -m "feat(agent): add config module with ~/.nomi/agent-config.json"
```

---

### Task 2: Screen Sensor

**Files:**
- Create: `desktop/src/main/agent/screen-sensor.ts`

- [ ] **Step 1: Create the screen sensor**

```typescript
// desktop/src/main/agent/screen-sensor.ts
import { desktopCapturer } from "electron";

export interface ScreenCapture {
  type: "screen";
  data: { imageBase64: string; width: number; height: number };
  timestamp: number;
}

let previousPixels: Uint8Array | null = null;

function computePixelDiff(current: Buffer, width: number, height: number): number {
  // Sample every 100th pixel for speed
  const currentArr = new Uint8Array(current);
  if (!previousPixels || previousPixels.length !== currentArr.length) {
    previousPixels = new Uint8Array(currentArr);
    return 1.0; // first capture = 100% different
  }
  let diffCount = 0;
  const sampleStep = 400; // every 100th pixel * 4 channels
  const totalSamples = Math.floor(currentArr.length / sampleStep);
  for (let i = 0; i < currentArr.length; i += sampleStep) {
    if (Math.abs(currentArr[i] - previousPixels[i]) > 20) diffCount++;
  }
  previousPixels = new Uint8Array(currentArr);
  return totalSamples > 0 ? diffCount / totalSamples : 0;
}

export async function captureScreen(): Promise<ScreenCapture | null> {
  try {
    const sources = await desktopCapturer.getSources({
      types: ["screen"],
      thumbnailSize: { width: 1280, height: 720 },
    });

    if (sources.length === 0) return null;

    const source = sources[0];
    const thumbnail = source.thumbnail;
    const size = thumbnail.getSize();
    const rawBitmap = thumbnail.toBitmap();

    // Check pixel difference
    const diff = computePixelDiff(rawBitmap, size.width, size.height);
    if (diff < 0.05) {
      return null; // less than 5% changed
    }

    const base64 = thumbnail.toJPEG(60).toString("base64");

    return {
      type: "screen",
      data: { imageBase64: base64, width: size.width, height: size.height },
      timestamp: Date.now(),
    };
  } catch (err) {
    console.error("[screen-sensor] Capture failed:", err);
    return null;
  }
}

export function resetPixelHistory(): void {
  previousPixels = null;
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd desktop && npx tsc -p tsconfig.main.json --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add desktop/src/main/agent/screen-sensor.ts
git commit -m "feat(agent): add screen sensor with pixel diff detection"
```

---

### Task 3: Clipboard Sensor

**Files:**
- Create: `desktop/src/main/agent/clipboard-sensor.ts`

- [ ] **Step 1: Create the clipboard sensor**

```typescript
// desktop/src/main/agent/clipboard-sensor.ts
import { clipboard } from "electron";

export interface ClipboardCapture {
  type: "clipboard";
  data: { text: string };
  timestamp: number;
}

let lastClipboardText = "";

export function checkClipboard(): ClipboardCapture | null {
  try {
    const text = clipboard.readText().trim();
    if (!text || text === lastClipboardText) return null;
    lastClipboardText = text;
    return {
      type: "clipboard",
      data: { text: text.slice(0, 100) }, // privacy: only first 100 chars
      timestamp: Date.now(),
    };
  } catch {
    return null;
  }
}

export function resetClipboardHistory(): void {
  lastClipboardText = "";
}
```

- [ ] **Step 2: Commit**

```bash
git add desktop/src/main/agent/clipboard-sensor.ts
git commit -m "feat(agent): add clipboard sensor"
```

---

### Task 4: App Sensor

**Files:**
- Create: `desktop/src/main/agent/app-sensor.ts`

- [ ] **Step 1: Create the app sensor**

```typescript
// desktop/src/main/agent/app-sensor.ts
import { exec } from "child_process";

export interface AppCapture {
  type: "app";
  data: { appName: string; windowTitle: string };
  timestamp: number;
}

let lastAppName = "";
let lastWindowTitle = "";

function getActiveWindow(): Promise<{ appName: string; windowTitle: string }> {
  return new Promise((resolve) => {
    // macOS: use AppleScript to get frontmost app and window title
    const script = `
      tell application "System Events"
        set frontApp to name of first application process whose frontmost is true
        set frontTitle to ""
        try
          set frontTitle to name of front window of (first application process whose frontmost is true)
        end try
      end tell
      return frontApp & "|" & frontTitle
    `;
    exec(`osascript -e '${script.replace(/'/g, "'\\''")}'`, (err, stdout) => {
      if (err) {
        resolve({ appName: "", windowTitle: "" });
        return;
      }
      const parts = stdout.trim().split("|");
      resolve({
        appName: parts[0] || "",
        windowTitle: parts.slice(1).join("|") || "",
      });
    });
  });
}

export async function checkActiveApp(): Promise<AppCapture | null> {
  try {
    const { appName, windowTitle } = await getActiveWindow();
    if (!appName) return null;
    if (appName === lastAppName && windowTitle === lastWindowTitle) return null;

    lastAppName = appName;
    lastWindowTitle = windowTitle;

    return {
      type: "app",
      data: { appName, windowTitle },
      timestamp: Date.now(),
    };
  } catch {
    return null;
  }
}

export function resetAppHistory(): void {
  lastAppName = "";
  lastWindowTitle = "";
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd desktop && npx tsc -p tsconfig.main.json --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add desktop/src/main/agent/app-sensor.ts
git commit -m "feat(agent): add app sensor with macOS AppleScript"
```

---

### Task 5: Local Analyzer (Ollama)

**Files:**
- Create: `desktop/src/main/agent/local-analyzer.ts`

- [ ] **Step 1: Create the Ollama analyzer**

```typescript
// desktop/src/main/agent/local-analyzer.ts
import { AgentConfig } from "./agent-config";

export interface AnalysisResult {
  scene: string;
  interesting: boolean;
  reason: string;
}

const recentScenes: string[] = [];
const MAX_RECENT = 5;

export async function analyzeScreen(
  imageBase64: string,
  appName: string,
  windowTitle: string,
  clipboardText: string | null,
  config: AgentConfig
): Promise<AnalysisResult | null> {
  const lastScene = recentScenes.length > 0 ? recentScenes[recentScenes.length - 1] : "无";

  const prompt = `你是一个桌面观察者。根据截图和上下文，简要描述用户在做什么，判断是否值得评论。

当前应用: ${appName}
窗口标题: ${windowTitle}
${clipboardText ? `剪贴板: ${clipboardText}` : ""}
上次场景: ${lastScene}

输出严格的JSON格式（不要包含其他文字）:
{"scene": "用户在做什么的简要描述", "interesting": true或false, "reason": "为什么值得或不值得评论"}

规则:
- 跟上次一样的场景 → interesting: false
- 用户切换了应用或在做新事情 → interesting: true
- 看到有趣的内容（视频、游戏、新闻、社交）→ interesting: true
- 纯打字没变化 → interesting: false`;

  try {
    const response = await fetch(`${config.ollamaUrl}/api/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: config.ollamaModel,
        prompt,
        images: [imageBase64],
        stream: false,
        options: { temperature: 0.3, num_predict: 200 },
      }),
    });

    if (!response.ok) {
      console.error("[analyzer] Ollama error:", response.status);
      return null;
    }

    const data = await response.json();
    const text = data.response || "";

    // Extract JSON from response
    const jsonMatch = text.match(/\{[\s\S]*\}/);
    if (!jsonMatch) {
      console.warn("[analyzer] No JSON in response:", text.slice(0, 100));
      return null;
    }

    const result: AnalysisResult = JSON.parse(jsonMatch[0]);

    // Dedup: check against recent scenes
    if (result.interesting) {
      const isDuplicate = recentScenes.some(
        (s) => s === result.scene || levenshteinSimilarity(s, result.scene) > 0.7
      );
      if (isDuplicate) {
        result.interesting = false;
        result.reason = "与最近的场景重复";
      }
    }

    // Update history
    recentScenes.push(result.scene);
    if (recentScenes.length > MAX_RECENT) recentScenes.shift();

    return result;
  } catch (err) {
    console.error("[analyzer] Failed:", err);
    return null;
  }
}

function levenshteinSimilarity(a: string, b: string): number {
  if (a === b) return 1;
  const longer = a.length > b.length ? a : b;
  const shorter = a.length > b.length ? b : a;
  if (longer.length === 0) return 1;
  // Simple character overlap ratio
  let matches = 0;
  for (const ch of shorter) {
    if (longer.includes(ch)) matches++;
  }
  return matches / longer.length;
}

export async function checkOllamaHealth(url: string): Promise<boolean> {
  try {
    const res = await fetch(`${url}/api/tags`, { signal: AbortSignal.timeout(3000) });
    return res.ok;
  } catch {
    return false;
  }
}

export function resetAnalyzerHistory(): void {
  recentScenes.length = 0;
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd desktop && npx tsc -p tsconfig.main.json --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add desktop/src/main/agent/local-analyzer.ts
git commit -m "feat(agent): add Ollama local analyzer with dedup"
```

---

### Task 6: Action Manager

**Files:**
- Create: `desktop/src/main/agent/action-manager.ts`

- [ ] **Step 1: Create the action manager**

```typescript
// desktop/src/main/agent/action-manager.ts
import { shell, Notification } from "electron";
import fs from "fs";
import { getBackendUrl } from "../backend";

export interface AgentAction {
  type: "search" | "open_url" | "notify" | "read_file";
  params: Record<string, string>;
}

export interface ActionResult {
  type: string;
  success: boolean;
  result?: string;
}

export async function executeAction(action: AgentAction): Promise<ActionResult> {
  switch (action.type) {
    case "open_url":
      return executeOpenUrl(action.params.url || "");
    case "notify":
      return executeNotify(action.params.title || "", action.params.body || "");
    case "search":
      return executeSearch(action.params.query || "");
    case "read_file":
      return executeReadFile(action.params.path || "");
    default:
      return { type: action.type, success: false, result: "Unknown action type" };
  }
}

function executeOpenUrl(url: string): ActionResult {
  if (!url) return { type: "open_url", success: false, result: "No URL" };
  try {
    shell.openExternal(url);
    return { type: "open_url", success: true, result: `Opened: ${url}` };
  } catch (err) {
    return { type: "open_url", success: false, result: String(err) };
  }
}

function executeNotify(title: string, body: string): ActionResult {
  try {
    new Notification({ title, body }).show();
    return { type: "notify", success: true };
  } catch (err) {
    return { type: "notify", success: false, result: String(err) };
  }
}

async function executeSearch(query: string): Promise<ActionResult> {
  if (!query) return { type: "search", success: false, result: "No query" };
  try {
    const backendUrl = getBackendUrl();
    const res = await fetch(`${backendUrl}/api/agent/search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    });
    if (!res.ok) return { type: "search", success: false, result: `HTTP ${res.status}` };
    const data = await res.json();
    return { type: "search", success: true, result: data.summary || "" };
  } catch (err) {
    return { type: "search", success: false, result: String(err) };
  }
}

function executeReadFile(filePath: string): ActionResult {
  if (!filePath) return { type: "read_file", success: false, result: "No path" };
  try {
    if (!fs.existsSync(filePath)) {
      return { type: "read_file", success: false, result: "File not found" };
    }
    const content = fs.readFileSync(filePath, "utf-8").slice(0, 2000); // limit to 2KB
    return { type: "read_file", success: true, result: content };
  } catch (err) {
    return { type: "read_file", success: false, result: String(err) };
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add desktop/src/main/agent/action-manager.ts
git commit -m "feat(agent): add action manager (search, open_url, notify, read_file)"
```

---

### Task 7: Sensor Manager — The Orchestrator

**Files:**
- Create: `desktop/src/main/agent/sensor-manager.ts`

- [ ] **Step 1: Create the sensor manager**

```typescript
// desktop/src/main/agent/sensor-manager.ts
import { getMainWindow } from "../index";
import { getBackendUrl } from "../backend";
import { AgentConfig, loadConfig, updateConfig } from "./agent-config";
import { captureScreen, resetPixelHistory } from "./screen-sensor";
import { checkClipboard, resetClipboardHistory } from "./clipboard-sensor";
import { checkActiveApp, resetAppHistory } from "./app-sensor";
import { analyzeScreen, checkOllamaHealth, resetAnalyzerHistory } from "./local-analyzer";
import { executeAction, AgentAction } from "./action-manager";

export type AgentStatus = "idle" | "sensing" | "analyzing" | "reacting" | "error";

let config: AgentConfig;
let screenTimer: ReturnType<typeof setInterval> | null = null;
let clipboardTimer: ReturnType<typeof setInterval> | null = null;
let appTimer: ReturnType<typeof setInterval> | null = null;
let lastReactionTime = 0;
let currentStatus: AgentStatus = "idle";
let lastClipboardText: string | null = null;

function sendToRenderer(channel: string, data: unknown): void {
  getMainWindow()?.webContents.send(channel, data);
}

function setStatus(status: AgentStatus): void {
  currentStatus = status;
  sendToRenderer("agent:status", { status });
}

async function handleScreenCapture(): Promise<void> {
  if (currentStatus !== "idle") return; // don't overlap

  setStatus("sensing");
  const capture = await captureScreen();
  if (!capture) {
    setStatus("idle");
    return;
  }

  // Also grab app info
  const appInfo = await checkActiveApp();
  const clipInfo = checkClipboard();
  if (clipInfo) lastClipboardText = clipInfo.data.text;

  setStatus("analyzing");
  const analysis = await analyzeScreen(
    capture.data.imageBase64,
    appInfo?.data.appName || "",
    appInfo?.data.windowTitle || "",
    lastClipboardText,
    config
  );

  if (!analysis || !analysis.interesting) {
    setStatus("idle");
    return;
  }

  // Rate limit
  const now = Date.now();
  if (now - lastReactionTime < config.minReactionIntervalSec * 1000) {
    console.log("[agent] Skipping reaction (rate limited)");
    setStatus("idle");
    return;
  }

  setStatus("reacting");
  lastReactionTime = now;

  // Call backend for character reaction
  try {
    const backendUrl = getBackendUrl();
    const res = await fetch(`${backendUrl}/api/agent/react`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        scene: analysis.scene,
        reason: analysis.reason,
        context: {
          active_app: appInfo?.data.appName || "",
          window_title: appInfo?.data.windowTitle || "",
          clipboard: lastClipboardText,
        },
      }),
    });

    if (!res.ok) {
      console.error("[agent] Backend react failed:", res.status);
      setStatus("idle");
      return;
    }

    const reaction = await res.json();
    sendToRenderer("agent:reaction", {
      text: reaction.reaction,
      text_ja: reaction.reaction_ja,
      emotion: reaction.emotion,
      type: "reaction",
    });

    // Execute action if LLM decided on one
    if (reaction.action) {
      const actionConfig = config as Record<string, unknown>;
      const actionType = reaction.action.type as string;
      const configKey = actionType === "search" ? "webSearch" :
                        actionType === "open_url" ? "openUrl" :
                        actionType === "notify" ? "notification" :
                        actionType === "read_file" ? "fileAccess" : "";

      const enabled = configKey && (actionConfig[configKey] as { enabled?: boolean })?.enabled !== false;
      if (enabled) {
        const result = await executeAction(reaction.action as AgentAction);
        sendToRenderer("agent:action-result", result);
      }
    }
  } catch (err) {
    console.error("[agent] Reaction error:", err);
  }

  setStatus("idle");
}

async function handleClipboardChange(): Promise<void> {
  if (!config.clipboardSensor.enabled) return;
  const capture = checkClipboard();
  if (capture) {
    lastClipboardText = capture.data.text;
    // Clipboard changes on their own don't trigger reactions
    // They enrich the next screen analysis
  }
}

async function handleAppChange(): Promise<void> {
  if (!config.appSensor.enabled) return;
  // App changes feed into the next screen analysis cycle
  await checkActiveApp();
}

export function startAgent(): void {
  config = loadConfig();
  console.log("[agent] Starting with config:", JSON.stringify(config, null, 2));

  if (config.screenSensor.enabled) {
    startScreenSensor();
  }
  if (config.clipboardSensor.enabled) {
    clipboardTimer = setInterval(handleClipboardChange, 2000);
  }
  if (config.appSensor.enabled) {
    appTimer = setInterval(handleAppChange, 3000);
  }
}

function startScreenSensor(): void {
  if (screenTimer) clearInterval(screenTimer);
  screenTimer = setInterval(handleScreenCapture, config.screenSensor.intervalSec * 1000);
  console.log(`[agent] Screen sensor started (${config.screenSensor.intervalSec}s interval)`);
}

function stopScreenSensor(): void {
  if (screenTimer) { clearInterval(screenTimer); screenTimer = null; }
}

export function stopAgent(): void {
  stopScreenSensor();
  if (clipboardTimer) { clearInterval(clipboardTimer); clipboardTimer = null; }
  if (appTimer) { clearInterval(appTimer); appTimer = null; }
  resetPixelHistory();
  resetClipboardHistory();
  resetAppHistory();
  resetAnalyzerHistory();
  setStatus("idle");
  console.log("[agent] Stopped");
}

export function applyConfig(partial: Partial<AgentConfig>): AgentConfig {
  const newConfig = updateConfig(partial);
  config = newConfig;

  // Restart sensors based on new config
  stopAgent();
  startAgent();

  return newConfig;
}

export function getAgentConfig(): AgentConfig {
  return config || loadConfig();
}

export function getStatus(): AgentStatus {
  return currentStatus;
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd desktop && npx tsc -p tsconfig.main.json --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add desktop/src/main/agent/sensor-manager.ts
git commit -m "feat(agent): add sensor manager orchestrator"
```

---

### Task 8: IPC + Preload Integration

**Files:**
- Modify: `desktop/src/main/ipc.ts`
- Modify: `desktop/src/preload/index.ts`
- Modify: `desktop/src/main/index.ts`

- [ ] **Step 1: Update IPC handlers**

```typescript
// desktop/src/main/ipc.ts — FULL REPLACEMENT
import { ipcMain } from "electron";
import { toggleExpand, getMainWindow } from "./index";
import { isBackendReady } from "./backend";
import { startAgent, stopAgent, applyConfig, getAgentConfig, getStatus } from "./agent/sensor-manager";

export function setupIPC(): void {
  ipcMain.handle("toggle-expand", () => {
    toggleExpand();
  });

  ipcMain.handle("minimize-to-tray", () => {
    getMainWindow()?.hide();
  });

  ipcMain.handle("get-backend-status", () => {
    return isBackendReady();
  });

  // Agent IPC
  ipcMain.handle("agent:get-config", () => {
    return getAgentConfig();
  });

  ipcMain.handle("agent:update-config", (_event, partial) => {
    return applyConfig(partial);
  });

  ipcMain.handle("agent:get-status", () => {
    return getStatus();
  });

  ipcMain.handle("agent:start", () => {
    startAgent();
  });

  ipcMain.handle("agent:stop", () => {
    stopAgent();
  });
}
```

- [ ] **Step 2: Update preload to expose agent APIs**

```typescript
// desktop/src/preload/index.ts — FULL REPLACEMENT
import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("nomi", {
  toggleExpand: () => ipcRenderer.invoke("toggle-expand"),
  minimize: () => ipcRenderer.invoke("minimize-to-tray"),
  getBackendStatus: () => ipcRenderer.invoke("get-backend-status"),
  onBackendReady: (callback: () => void) => {
    ipcRenderer.on("backend-ready", callback);
    return () => { ipcRenderer.removeListener("backend-ready", callback); };
  },

  // Agent APIs
  agent: {
    getConfig: () => ipcRenderer.invoke("agent:get-config"),
    updateConfig: (partial: Record<string, unknown>) => ipcRenderer.invoke("agent:update-config", partial),
    getStatus: () => ipcRenderer.invoke("agent:get-status"),
    start: () => ipcRenderer.invoke("agent:start"),
    stop: () => ipcRenderer.invoke("agent:stop"),
    onReaction: (callback: (data: unknown) => void) => {
      ipcRenderer.on("agent:reaction", (_e, data) => callback(data));
      return () => { ipcRenderer.removeAllListeners("agent:reaction"); };
    },
    onStatus: (callback: (data: unknown) => void) => {
      ipcRenderer.on("agent:status", (_e, data) => callback(data));
      return () => { ipcRenderer.removeAllListeners("agent:status"); };
    },
    onActionResult: (callback: (data: unknown) => void) => {
      ipcRenderer.on("agent:action-result", (_e, data) => callback(data));
      return () => { ipcRenderer.removeAllListeners("agent:action-result"); };
    },
  },
});
```

- [ ] **Step 3: Update index.ts to initialize agent**

Add to `desktop/src/main/index.ts` after `startBackend();` inside `app.whenReady()`:

```typescript
  // Start agent (sensors will only run if enabled in config)
  import { startAgent, stopAgent } from "./agent/sensor-manager";
  startAgent();
```

Add to `app.on("will-quit")`:

```typescript
  stopAgent();
```

- [ ] **Step 4: Verify TypeScript compiles**

Run: `cd desktop && npx tsc -p tsconfig.main.json --noEmit`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add desktop/src/main/ipc.ts desktop/src/preload/index.ts desktop/src/main/index.ts
git commit -m "feat(agent): wire up IPC and preload for agent APIs"
```

---

### Task 9: Backend — `/api/agent/react` and `/api/agent/search`

**Files:**
- Modify: `backend/app/api/agents.py`

- [ ] **Step 1: Add react and search endpoints**

Append to `backend/app/api/agents.py`:

```python
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
    # Find the robot
    robot = None
    if body.robot_id:
        result = await session.execute(
            select(Robot).where(Robot.id == uuid.UUID(body.robot_id))
        )
        robot = result.scalar_one_or_none()

    if not robot:
        # Default to first robot
        result = await session.execute(
            select(Robot).where(Robot.user_id == DEFAULT_USER_ID).limit(1)
        )
        robot = result.scalar_one_or_none()

    if not robot:
        return {"reaction": "", "reaction_ja": "", "emotion": "Normal", "action": None}

    # Build character prompt
    personality = robot.personality or []
    personality_str = "、".join(str(p) for p in personality[:5]) if personality else "冷静"
    name = robot.name

    recent = body.context.get("recent_reactions", [])
    recent_str = "\n".join(f"- {r}" for r in recent[-3:]) if recent else "无"

    system_prompt = f"""你是{name}。性格：{personality_str}。
你正在观察旅伴（用户）的桌面活动，以你的性格做出简短反应。

规则：
- 保持角色性格，用角色的口吻说话
- 一两句话就够，简短自然
- 如果场景跟你有关（比如用户在看你的故事），可以更感兴趣
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

    llm = create_llm(settings.llm_provider)
    raw = await llm.generate(user_prompt, system_prompt=system_prompt, model="deepseek-v4-flash")

    # Parse JSON from response
    import re
    json_match = re.search(r'\{[\s\S]*\}', raw)
    if not json_match:
        return {"reaction": raw.strip(), "reaction_ja": "", "emotion": "Normal", "action": None}

    try:
        result = json.loads(json_match.group())
        return {
            "reaction": result.get("reaction", ""),
            "reaction_ja": result.get("reaction_ja", ""),
            "emotion": result.get("emotion", "Normal"),
            "action": result.get("action"),
        }
    except json.JSONDecodeError:
        return {"reaction": raw.strip(), "reaction_ja": "", "emotion": "Normal", "action": None}


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
        result = await session.execute(
            select(Robot).where(Robot.id == uuid.UUID(body.robot_id))
        )
        robot = result.scalar_one_or_none()

    if not robot:
        result = await session.execute(
            select(Robot).where(Robot.user_id == DEFAULT_USER_ID).limit(1)
        )
        robot = result.scalar_one_or_none()

    if not robot:
        return {"query": body.query, "summary": "No robot available"}

    search_result = await search_topic(robot, body.query)
    return search_result or {"query": body.query, "summary": "Search returned no results"}
```

- [ ] **Step 2: Add missing import**

At the top of `agents.py`, add `from pydantic import BaseModel` if not already present (it is imported via `app.schemas` — verify, otherwise add).

- [ ] **Step 3: Verify backend starts**

Run: `pm2 restart nomi-backend && sleep 3 && curl -s http://127.0.0.1:8100/api/status`
Expected: `{"status": "ok"}`

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/agents.py
git commit -m "feat(agent): add /api/agent/react and /api/agent/search endpoints"
```

---

### Task 10: Renderer — AgentSettings Component

**Files:**
- Create: `desktop/src/renderer/components/AgentSettings.tsx`

- [ ] **Step 1: Create the settings panel**

```tsx
// desktop/src/renderer/components/AgentSettings.tsx
import { useEffect, useState } from "react";

interface AgentConfig {
  screenSensor: { enabled: boolean; intervalSec: number };
  clipboardSensor: { enabled: boolean };
  appSensor: { enabled: boolean };
  webSearch: { enabled: boolean };
  notification: { enabled: boolean };
  fileAccess: { enabled: boolean };
  openUrl: { enabled: boolean };
  voice: { enabled: boolean };
  minReactionIntervalSec: number;
  ollamaModel: string;
  ollamaUrl: string;
}

interface Props {
  onClose: () => void;
}

export function AgentSettings({ onClose }: Props) {
  const [config, setConfig] = useState<AgentConfig | null>(null);

  useEffect(() => {
    window.nomi.agent.getConfig().then(setConfig);
  }, []);

  async function toggle(path: string, value: boolean) {
    if (!config) return;
    const parts = path.split(".");
    let update: Record<string, unknown> = {};
    if (parts.length === 2) {
      update = { [parts[0]]: { ...(config as any)[parts[0]], [parts[1]]: value } };
    } else {
      update = { [parts[0]]: value };
    }
    const newConfig = await window.nomi.agent.updateConfig(update);
    setConfig(newConfig);
  }

  async function setInterval(sec: number) {
    if (!config) return;
    const newConfig = await window.nomi.agent.updateConfig({
      screenSensor: { ...config.screenSensor, intervalSec: sec },
    });
    setConfig(newConfig);
  }

  async function setMinInterval(sec: number) {
    const newConfig = await window.nomi.agent.updateConfig({ minReactionIntervalSec: sec });
    setConfig(newConfig);
  }

  if (!config) return null;

  const Toggle = ({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) => (
    <label className="flex items-center justify-between py-1.5">
      <span className="text-[13px] text-gray-700">{label}</span>
      <div
        onClick={() => onChange(!checked)}
        className={`w-9 h-5 rounded-full cursor-pointer transition-colors ${checked ? "bg-purple-400" : "bg-gray-300"}`}
      >
        <div className={`w-4 h-4 mt-0.5 rounded-full bg-white shadow transition-transform ${checked ? "translate-x-4.5" : "translate-x-0.5"}`} />
      </div>
    </label>
  );

  return (
    <div className="absolute inset-0 z-50 bg-black/20 flex items-center justify-center" onClick={onClose}>
      <div className="bg-white/90 backdrop-blur-lg rounded-2xl shadow-xl border border-white/50 w-[320px] max-h-[480px] overflow-y-auto p-5" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-[15px] font-bold text-gray-800">Agent 设置</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg">x</button>
        </div>

        <p className="text-[11px] text-gray-400 mb-2">感知功能</p>
        <Toggle label="👁 屏幕感知" checked={config.screenSensor.enabled} onChange={(v) => toggle("screenSensor.enabled", v)} />
        {config.screenSensor.enabled && (
          <div className="ml-6 mb-1">
            <span className="text-[11px] text-gray-400 mr-2">频率</span>
            <select
              value={config.screenSensor.intervalSec}
              onChange={(e) => setInterval(Number(e.target.value))}
              className="text-[12px] bg-gray-100 rounded px-1.5 py-0.5"
            >
              {[10, 30, 60, 120].map((s) => <option key={s} value={s}>{s}s</option>)}
            </select>
          </div>
        )}
        <Toggle label="📋 剪贴板感知" checked={config.clipboardSensor.enabled} onChange={(v) => toggle("clipboardSensor.enabled", v)} />
        <Toggle label="📱 应用切换感知" checked={config.appSensor.enabled} onChange={(v) => toggle("appSensor.enabled", v)} />

        <div className="border-t border-gray-100 my-3" />
        <p className="text-[11px] text-gray-400 mb-2">动作功能</p>
        <Toggle label="🔍 网页搜索" checked={config.webSearch.enabled} onChange={(v) => toggle("webSearch.enabled", v)} />
        <Toggle label="🔔 系统通知" checked={config.notification.enabled} onChange={(v) => toggle("notification.enabled", v)} />
        <Toggle label="📂 文件访问" checked={config.fileAccess.enabled} onChange={(v) => toggle("fileAccess.enabled", v)} />
        <Toggle label="🌐 打开网页/应用" checked={config.openUrl.enabled} onChange={(v) => toggle("openUrl.enabled", v)} />

        <div className="border-t border-gray-100 my-3" />
        <p className="text-[11px] text-gray-400 mb-2">输出</p>
        <Toggle label="🔊 语音播放" checked={config.voice.enabled} onChange={(v) => toggle("voice.enabled", v)} />
        <label className="flex items-center justify-between py-1.5">
          <span className="text-[13px] text-gray-700">💬 最小打扰间隔</span>
          <select
            value={config.minReactionIntervalSec}
            onChange={(e) => setMinInterval(Number(e.target.value))}
            className="text-[12px] bg-gray-100 rounded px-1.5 py-0.5"
          >
            {[30, 60, 120, 300, 600].map((s) => <option key={s} value={s}>{s >= 60 ? `${s / 60}min` : `${s}s`}</option>)}
          </select>
        </label>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add desktop/src/renderer/components/AgentSettings.tsx
git commit -m "feat(agent): add AgentSettings UI component"
```

---

### Task 11: Renderer — Integrate Agent into App.tsx

**Files:**
- Modify: `desktop/src/renderer/App.tsx`

- [ ] **Step 1: Add agent type declarations**

Update the `Window` interface in `App.tsx`:

```typescript
declare global {
  interface Window {
    nomi: {
      toggleExpand: () => void;
      minimize: () => void;
      getBackendStatus: () => Promise<boolean>;
      onBackendReady: (callback: () => void) => () => void;
      agent: {
        getConfig: () => Promise<Record<string, unknown>>;
        updateConfig: (partial: Record<string, unknown>) => Promise<Record<string, unknown>>;
        getStatus: () => Promise<string>;
        start: () => Promise<void>;
        stop: () => Promise<void>;
        onReaction: (callback: (data: { text: string; text_ja: string; emotion: string; type: string }) => void) => () => void;
        onStatus: (callback: (data: { status: string }) => void) => () => void;
        onActionResult: (callback: (data: { type: string; success: boolean; result?: string }) => void) => () => void;
      };
    };
  }
}
```

- [ ] **Step 2: Add agent state and listeners**

Add these state variables and effects inside the `App` component:

```typescript
const [showAgentSettings, setShowAgentSettings] = useState(false);
const [agentStatus, setAgentStatus] = useState<string>("idle");

// Listen for agent reactions
useEffect(() => {
  if (!window.nomi?.agent) return;

  const cleanupReaction = window.nomi.agent.onReaction((data) => {
    // Add reaction as a chat message with special type
    const reactionMsg: ChatMessage = {
      id: `reaction-${Date.now()}`,
      sender_type: "robot",
      sender_id: robot?.id || null,
      sender_name: robot?.name || "Agent",
      content: data.text,
      emotion: null,
      created_at: new Date().toISOString(),
      _japanese: data.text_ja,
      _emotion: data.emotion,
      _isReaction: true,
    };
    if (robot) {
      const current = getChatState();
      updateChatState({ messages: [...current.messages, reactionMsg] });
      setMsgVersion((v) => v + 1);
    }

    // Set avatar emotion
    const emotionState = data.emotion === "Sad" ? "sad"
      : data.emotion === "Surprised" ? "surprised"
      : data.emotion === "Happy" ? "happy"
      : "speaking";
    setCharacterState(emotionState as CharacterState);

    // Auto-play TTS if voice enabled
    if (data.text_ja) {
      api.speak(data.text_ja, robot?.name || "", data.emotion || "Normal")
        .catch(console.error)
        .finally(() => setCharacterState("idle"));
    } else {
      setTimeout(() => setCharacterState("idle"), 3000);
    }
  });

  const cleanupStatus = window.nomi.agent.onStatus((data) => {
    setAgentStatus(data.status);
  });

  return () => { cleanupReaction(); cleanupStatus(); };
}, [robot]);
```

- [ ] **Step 3: Add settings button and status indicator to the UI**

In the left column, after the character name section, add:

```tsx
{/* Agent status + settings button */}
<div className="flex items-center gap-2 py-1">
  <span className="text-[10px] text-gray-400">
    {agentStatus === "idle" ? "" : agentStatus === "sensing" ? "👁" : agentStatus === "analyzing" ? "🔍" : agentStatus === "reacting" ? "⚡" : "❌"}
  </span>
  <button
    onClick={() => setShowAgentSettings(true)}
    className="w-6 h-6 flex items-center justify-center rounded-md hover:bg-white/50 transition-colors text-gray-400 hover:text-gray-600"
    title="Agent 设置"
  >
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  </button>
</div>
```

At the end of the component, before the closing `</div>`, add:

```tsx
{showAgentSettings && (
  <AgentSettings onClose={() => setShowAgentSettings(false)} />
)}
```

Add import at top: `import { AgentSettings } from "./components/AgentSettings";`

- [ ] **Step 4: Add `_isReaction` to ChatMessage type**

In `desktop/src/renderer/types.ts`, add to `ChatMessage`:

```typescript
  _isReaction?: boolean;
```

- [ ] **Step 5: Style reaction bubbles differently in ChatBubble.tsx**

In `ChatBubble.tsx`, the bot message card: if `_isReaction` is true, add a light purple tint and 👁 icon. Pass `isReaction` as a prop.

- [ ] **Step 6: Build and test**

Run: `cd desktop && npm run build`
Expected: Build succeeds

- [ ] **Step 7: Commit**

```bash
git add desktop/src/renderer/
git commit -m "feat(agent): integrate agent reactions, settings, and status into UI"
```

---

### Task 12: Download Ollama Vision Model

- [ ] **Step 1: Pull minicpm-v**

Run: `ollama pull minicpm-v`
Expected: Model downloaded (~3.1GB)

- [ ] **Step 2: Verify**

Run: `ollama list | grep minicpm`
Expected: Shows `minicpm-v` in the list

---

### Task 13: End-to-End Test

- [ ] **Step 1: Start all services**

```bash
pm2 restart nomi-backend
ollama serve &  # if not already running
```

- [ ] **Step 2: Build and launch desktop app**

```bash
cd desktop && npm run build && npx electron .
```

- [ ] **Step 3: Enable screen sensor**

Open Agent Settings → toggle "屏幕感知" on → set interval to 10s for testing

- [ ] **Step 4: Verify flow**

- Switch between apps and wait 10s
- Check console for `[agent]` logs
- Verify Ollama analysis runs
- Verify character reaction appears in chat panel
- Verify TTS plays the reaction

- [ ] **Step 5: Test each sensor and action**

- Toggle clipboard sensor → copy text → verify it enriches next reaction
- Toggle app sensor → switch apps → verify detection
- Test web search via chat
- Test notification

- [ ] **Step 6: Commit final state**

```bash
git add -A
git commit -m "feat(agent): complete desktop agent with screen sensing, Ollama analysis, and character reactions"
```
