import { ROBOT_VOICE_MAP } from "./types";

const BACKEND_URL = "http://127.0.0.1:8100";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BACKEND_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

/** Parse bot reply: extract emotion, Chinese text, Japanese text */
export function parseBotReply(raw: string): {
  emotion: string;
  chinese: string;
  japanese: string;
} {
  const emotionMatch = raw.match(/\[emotion:(\w+)\]/);
  const emotion = emotionMatch?.[1] || "Normal";

  const chineseMatch = raw.match(/中文[：:]\s*(.+)/);
  const japaneseMatch = raw.match(/日本語[：:]\s*(.+)/);

  const chinese = chineseMatch?.[1]?.trim() || raw.replace(/\[emotion:\w+\]/, "").trim();
  const japanese = japaneseMatch?.[1]?.trim() || "";

  return { emotion, chinese, japanese };
}

function _playAudio(blob: Blob): Promise<void> {
  const audioUrl = URL.createObjectURL(blob);
  const audio = new Audio(audioUrl);
  return new Promise((resolve, reject) => {
    audio.onloadedmetadata = () => {
      console.log(`[TTS] Audio duration: ${audio.duration}s`);
    };
    audio.onended = () => {
      console.log(`[TTS] Playback ended at ${audio.currentTime}s`);
      URL.revokeObjectURL(audioUrl);
      resolve();
    };
    audio.onerror = (e) => {
      console.error(`[TTS] Audio error:`, e);
      URL.revokeObjectURL(audioUrl);
      reject(e);
    };
    audio.play().catch((e) => {
      console.error(`[TTS] Play failed:`, e);
      reject(e);
    });
  });
}

export const api = {
  listRobots: () => request<import("./types").Robot[]>("/api/robots?desktop=true"),

  createConversation: () =>
    request<{ id: string }>("/api/conversations", { method: "POST" }),

  sendMessage: (conversationId: string, content: string, model: string, robotId?: string) => {
    let url = `/api/conversations/${conversationId}/message?model=${model}`;
    if (robotId) url += `&robot_id=${robotId}`;
    return request<{ messages: import("./types").ChatMessage[] }>(url, {
      method: "POST",
      body: JSON.stringify({ content }),
    });
  },

  getLatestConversation: () =>
    request<import("./types").Conversation | null>("/api/conversations/latest"),

  getStatus: () => request<{ status: string }>("/api/status"),

  agentChat: (message: string, robotId: string, conversationId?: string, activeApp?: string, windowTitle?: string, screenDescription?: string) => {
    const body: Record<string, string> = { message, robot_id: robotId };
    if (conversationId) body.conversation_id = conversationId;
    if (activeApp) body.active_app = activeApp;
    if (windowTitle) body.window_title = windowTitle;
    if (screenDescription) body.screen_description = screenDescription;
    return request<{
      reply: string;
      reply_ja: string;
      emotion: string;
      desktop_actions: Array<{ type: string; params: Record<string, string> }>;
      tools_called: string[];
    }>("/api/agents/chat", {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  /** Trigger a character reaction to a desktop observation */
  agentReact: (scene: string, reason: string, robotId: string, context: Record<string, string> = {}) =>
    request<{
      reaction: string;
      reaction_ja: string;
      emotion: string;
      action: { type: string; params: Record<string, string> } | null;
    }>("/api/agents/react", {
      method: "POST",
      body: JSON.stringify({ scene, reason, robot_id: robotId, context }),
    }),

  /** Fetch TTS audio as a blob without playing it */
  fetchTtsBlob: async (text: string, robotName: string, emotion: string = "Normal"): Promise<Blob | null> => {
    const character = ROBOT_VOICE_MAP[robotName] || "frieren";
    const url = `${BACKEND_URL}/api/tts/speak-genie?text=${encodeURIComponent(text)}&emotion=${encodeURIComponent(emotion)}&character=${encodeURIComponent(character)}&lang=auto`;
    console.log(`[TTS] Fetching: ${url.slice(0, 100)}...`);
    const res = await fetch(url);
    console.log(`[TTS] Response: ${res.status}, size=${res.headers.get("content-length")}`);
    if (!res.ok) throw new Error(`TTS error: ${res.status}`);
    const blob = await res.blob();
    console.log(`[TTS] Blob size: ${blob.size}`);
    if (blob.size < 1000) {
      console.warn("[TTS] Audio too small, skipping");
      return null;
    }
    return blob;
  },

  /** Speak text with a specific character's voice (fetch + play) */
  speak: async (text: string, robotName: string, emotion: string = "Normal"): Promise<void> => {
    const blob = await api.fetchTtsBlob(text, robotName, emotion);
    if (!blob) return;
    await _playAudio(blob);
  },
};
