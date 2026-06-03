import { shell, Notification } from "electron";
import { app } from "electron";
import fs from "fs";
import path from "path";
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
    const parsed = new URL(url);
    if (!["http:", "https:"].includes(parsed.protocol)) {
      return { type: "open_url", success: false, result: "Protocol not allowed" };
    }
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
    const res = await fetch(`${backendUrl}/api/agents/search`, {
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
    const resolved = path.resolve(filePath);
    const allowedBase = path.join(app.getPath("home"), "Documents");
    if (!resolved.startsWith(allowedBase)) {
      return { type: "read_file", success: false, result: "Path not allowed (only ~/Documents)" };
    }
    if (!fs.existsSync(resolved)) {
      return { type: "read_file", success: false, result: "File not found" };
    }
    const content = fs.readFileSync(resolved, "utf-8").slice(0, 2000);
    return { type: "read_file", success: true, result: content };
  } catch (err) {
    return { type: "read_file", success: false, result: String(err) };
  }
}
