import { ipcMain, app as electronApp } from "electron";
import { toggleExpand, getMainWindow } from "./index";
import { isBackendReady } from "./backend";
import { startAgent, stopAgent, applyConfig, getAgentConfig, getStatus } from "./agent/sensor-manager";
import { executeAction } from "./agent/action-manager";
import { checkActiveApp } from "./agent/app-sensor";
// NomiScreenshot.app handles capture, ocr.swift handles text recognition

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

  ipcMain.handle("agent:get-desktop-context", async () => {
    const app = await checkActiveApp();
    const activeApp = app?.data.appName || "";
    const windowTitle = app?.data.windowTitle || "";

    // Capture screenshot + OCR using macOS native Vision framework
    let screenDescription = "";
    try {
      console.log("[ipc] Capturing screenshot...");
      const { execSync } = require("child_process");
      const fs = require("fs");
      const path = require("path");
      const tmpImg = require("os").tmpdir() + "/nomi-screen.jpg";
      // Tools (NomiScreenshot.app, ocr.swift) must live on the real filesystem, not inside asar.
      // Packaged: bundled via extraResources -> Contents/Resources/tools/
      // Dev: __dirname = dist/main/main/ -> 3 levels up to desktop/, then tools/
      const toolsDir = electronApp.isPackaged
        ? path.join(process.resourcesPath, "tools")
        : path.resolve(__dirname, "..", "..", "..", "tools");
      const appPath = path.join(toolsDir, "NomiScreenshot.app");
      const ocrScript = path.join(toolsDir, "ocr.swift");

      // Just capture screen as-is (including our window)
      const win = getMainWindow();

      try { fs.unlinkSync(tmpImg); } catch {}
      execSync(`open "${appPath}" --args "${tmpImg}"`, { timeout: 8000 });
      // Wait for file
      for (let i = 0; i < 20; i++) {
        if (fs.existsSync(tmpImg) && fs.statSync(tmpImg).size > 1000) break;
        execSync("sleep 0.3");
      }


      if (fs.existsSync(tmpImg) && fs.statSync(tmpImg).size > 1000) {
        console.log("[ipc] Screenshot saved, running OCR...");

        // Step 2: OCR using macOS Vision framework (no special permissions needed)
        const ocrResult = execSync(`swift "${ocrScript}" "${tmpImg}"`, {
          timeout: 15000,
          encoding: "utf-8",
        }).trim();

        if (ocrResult) {
          screenDescription = `当前应用: ${activeApp}\n窗口标题: ${windowTitle}\n屏幕上的文字内容:\n${ocrResult}`;
          console.log("[ipc] OCR result:", ocrResult.slice(0, 200));
        }

        try { fs.unlinkSync(tmpImg); } catch {}
      } else {
        console.warn("[ipc] Screenshot capture failed");
      }
    } catch (err) {
      console.warn("[ipc] Screen capture/OCR skipped:", (err as Error).message);
    }

    return { activeApp, windowTitle, screenDescription };
  });

  ipcMain.handle("agent:execute-action", async (_event, action) => {
    // Map open_browser to open_url for the existing action manager
    if (action.type === "open_browser") {
      action = { ...action, type: "open_url" };
    }
    return executeAction(action);
  });
}
