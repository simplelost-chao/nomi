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
  if (currentStatus !== "idle") return;

  setStatus("sensing");
  const capture = await captureScreen();
  if (!capture) {
    setStatus("idle");
    return;
  }

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

  const now = Date.now();
  if (now - lastReactionTime < config.minReactionIntervalSec * 1000) {
    console.log("[agent] Skipping reaction (rate limited)");
    setStatus("idle");
    return;
  }

  setStatus("reacting");
  lastReactionTime = now;

  try {
    const backendUrl = getBackendUrl();
    const res = await fetch(`${backendUrl}/api/agents/react`, {
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

    if (reaction.action) {
      const actionConfig = config as unknown as Record<string, unknown>;
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
  }
}

async function handleAppChange(): Promise<void> {
  if (!config.appSensor.enabled) return;
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

// Re-export for external use
export { checkOllamaHealth };
