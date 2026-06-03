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
