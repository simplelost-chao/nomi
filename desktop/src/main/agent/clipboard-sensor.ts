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
      data: { text: text.slice(0, 100) },
      timestamp: Date.now(),
    };
  } catch {
    return null;
  }
}

export function resetClipboardHistory(): void {
  lastClipboardText = "";
}
