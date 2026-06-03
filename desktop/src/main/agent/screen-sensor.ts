import { desktopCapturer, app } from "electron";

export interface ScreenCapture {
  type: "screen";
  data: { imageBase64: string; width: number; height: number };
  timestamp: number;
}

let previousPixels: Uint8Array | null = null;

function computePixelDiff(current: Buffer, width: number, height: number): number {
  const currentArr = new Uint8Array(current);
  if (!previousPixels || previousPixels.length !== currentArr.length) {
    previousPixels = new Uint8Array(currentArr);
    return 1.0;
  }
  let diffCount = 0;
  const sampleStep = 400;
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

    const diff = computePixelDiff(rawBitmap, size.width, size.height);
    if (diff < 0.05) {
      return null;
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

export async function captureScreenNow(): Promise<string | null> {
  // Method 1: desktopCapturer (Electron built-in)
  try {
    const sources = await desktopCapturer.getSources({
      types: ["screen"],
      thumbnailSize: { width: 1280, height: 720 },
    });
    if (sources.length > 0) {
      const base64 = sources[0].thumbnail.toJPEG(60).toString("base64");
      console.log(`[screen] captured via desktopCapturer: ${base64.length} chars`);
      return base64;
    }
  } catch (err) {
    console.warn("[screen] desktopCapturer failed:", (err as Error).message);
  }

  // Method 2: NomiScreenshot.app via `open` (proper macOS app identity for TCC)
  try {
    const { execSync } = require("child_process");
    const fs = require("fs");
    const path = require("path");
    const tmpPath = require("os").tmpdir() + "/nomi-screen.jpg";
    // Tools live on the real filesystem (not asar). Packaged: extraResources -> Contents/Resources/tools/
    // Dev: dist/main/main/agent/ -> 4 levels up to desktop/, then tools/
    const toolsDir = app.isPackaged
      ? path.join(process.resourcesPath, "tools")
      : path.resolve(__dirname, "..", "..", "..", "..", "tools");
    const appPath = path.join(toolsDir, "NomiScreenshot.app");
    // Remove old file first
    try { fs.unlinkSync(tmpPath); } catch {}
    execSync(`open "${appPath}" --args "${tmpPath}"`, { timeout: 8000 });
    // Wait for the app to finish writing
    for (let i = 0; i < 20; i++) {
      if (fs.existsSync(tmpPath) && fs.statSync(tmpPath).size > 1000) break;
      execSync("sleep 0.3");
    }
    if (fs.existsSync(tmpPath) && fs.statSync(tmpPath).size > 1000) {
      const buf = fs.readFileSync(tmpPath);
      fs.unlinkSync(tmpPath);
      const base64 = buf.toString("base64");
      console.log(`[screen] captured via NomiScreenshot.app: ${base64.length} chars`);
      return base64;
    }
    console.warn("[screen] NomiScreenshot.app produced no output");
  } catch (err) {
    console.warn("[screen] NomiScreenshot.app failed:", (err as Error).message);
  }

  // Method 3: screencapture CLI
  try {
    const { execSync } = require("child_process");
    const fs = require("fs");
    const tmpPath = require("os").tmpdir() + "/nomi-screen.jpg";
    execSync(`screencapture -x -t jpg "${tmpPath}"`, { timeout: 5000 });
    const buf = fs.readFileSync(tmpPath);
    fs.unlinkSync(tmpPath);
    const base64 = buf.toString("base64");
    console.log(`[screen] captured via screencapture: ${base64.length} chars`);
    return base64;
  } catch (err) {
    console.error("[screen] all capture methods failed:", (err as Error).message);
    return null;
  }
}

export function resetPixelHistory(): void {
  previousPixels = null;
}
