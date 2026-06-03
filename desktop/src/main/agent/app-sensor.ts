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
