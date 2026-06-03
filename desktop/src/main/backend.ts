import { ChildProcess, spawn } from "child_process";
import { existsSync } from "fs";
import path from "path";
import { app } from "electron";
import { getMainWindow } from "./index";

let backendProcess: ChildProcess | null = null;
let backendReady = false;
const BACKEND_PORT = 8100;
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;

export function getBackendUrl(): string {
  return BACKEND_URL;
}

export function isBackendReady(): boolean {
  return backendReady;
}

function getServerPath(): string {
  if (process.env.NODE_ENV === "development") {
    return path.join(
      app.getAppPath(),
      "..",
      "backend",
      "desktop",
      "dist",
      "nomi-server"
    );
  }
  return path.join(process.resourcesPath, "backend", "nomi-server");
}

export function startBackend(): void {
  const serverPath = getServerPath();
  console.log(`[backend] Starting: ${serverPath}`);

  if (!existsSync(serverPath)) {
    console.warn(`[backend] Binary not found at ${serverPath}, skipping. Run 'python backend/desktop/build.py' to build it.`);
    // Still poll in case backend is already running externally
    pollBackendHealth();
    return;
  }

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

    pollBackendHealth();
  } catch (err) {
    console.error(`[backend] Failed to start: ${err}`);
  }
}

export function stopBackend(): void {
  if (backendProcess && !backendProcess.killed) {
    console.log("[backend] Stopping...");
    backendProcess.kill("SIGTERM");
    setTimeout(() => {
      if (backendProcess && !backendProcess.killed) {
        backendProcess.kill("SIGKILL");
      }
    }, 3000);
  }
}

async function pollBackendHealth(): Promise<void> {
  const maxAttempts = 30;
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
