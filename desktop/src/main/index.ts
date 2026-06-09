import { app, BrowserWindow, globalShortcut, screen, systemPreferences, session } from "electron";
import path from "path";
import { setupTray } from "./tray";
import { startBackend, stopBackend, isBackendReady } from "./backend";
import { setupIPC } from "./ipc";
import { startAgent, stopAgent } from "./agent/sensor-manager";

let mainWindow: BrowserWindow | null = null;

const WINDOW_SIZE = { width: 680, height: 520 };

function createWindow() {
  mainWindow = new BrowserWindow({
    width: WINDOW_SIZE.width,
    height: WINDOW_SIZE.height,
    frame: false,
    titleBarStyle: "hidden",
    trafficLightPosition: { x: -100, y: -100 },  // Hide traffic lights
    transparent: true,
    alwaysOnTop: true,
    resizable: true,
    hasShadow: true,
    roundedCorners: true,
    backgroundColor: "#00000000",
    skipTaskbar: true,
    webPreferences: {
      preload: path.join(__dirname, "..", "preload", "index.js"),
      contextIsolation: true,
      nodeIntegration: false,
      devTools: true,
    },
  });

  const display = screen.getPrimaryDisplay();
  const { width, height } = display.workAreaSize;
  mainWindow.setPosition(
    width - WINDOW_SIZE.width - 20,
    height - WINDOW_SIZE.height - 20
  );

  if (process.env.NODE_ENV === "development") {
    mainWindow.loadURL("http://localhost:5173");
  } else {
    mainWindow.loadFile(path.join(__dirname, "..", "..", "renderer", "index.html"));
  }


  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

export function toggleExpand() {
  // No-op: window stays at fixed size, UI toggles internally
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
  // Grant the renderer's permission requests (esp. getUserMedia / microphone for the
  // press-to-talk voice button). Without this, Electron denies media in the renderer
  // even when the OS-level mic is granted (NotAllowedError). This is a local, trusted
  // app loading its own bundled content, so granting all renderer requests is safe.
  session.defaultSession.setPermissionRequestHandler((_wc, _permission, callback) => callback(true));
  session.defaultSession.setPermissionCheckHandler(() => true);

  createWindow();
  setupIPC();
  setupTray();

  globalShortcut.register("CommandOrControl+Shift+N", () => {
    if (mainWindow?.isVisible()) {
      hideWindow();
    } else {
      showWindow();
    }
  });

  // Request microphone permission
  if (process.platform === "darwin") {
    systemPreferences.askForMediaAccess("microphone").then((granted) => {
      console.log(`[app] Microphone access: ${granted}`);
    });

    // Check screen recording permission and trigger prompt if needed
    const screenAccess = systemPreferences.getMediaAccessStatus("screen");
    console.log(`[app] Screen recording access: ${screenAccess}`);
    if (screenAccess !== "granted") {
      console.log("[app] Requesting screen recording permission...");
      // Use native CGRequestScreenCaptureAccess to trigger the system prompt
      try {
        const { execSync } = require("child_process");
        execSync(`swift -e 'import CoreGraphics; CGRequestScreenCaptureAccess()'`, { timeout: 5000 });
      } catch {}
      // Also attempt a capture to register in TCC
      const { desktopCapturer } = require("electron");
      desktopCapturer.getSources({ types: ["screen"], thumbnailSize: { width: 1, height: 1 } }).catch(() => {});
    }
  }

  startBackend();
  startAgent();
});

app.on("will-quit", () => {
  globalShortcut.unregisterAll();
  stopAgent();
  stopBackend();
});

app.on("window-all-closed", () => {
  // Prevent app from quitting when all windows are closed
});
