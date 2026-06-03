const API_URL = process.env.NEXT_PUBLIC_API_URL || "";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export const api = {
  createRobots: (count = 3, preferences?: string) =>
    request<import("./types").Robot[]>("/api/robots", {
      method: "POST",
      body: JSON.stringify({ count, preferences }),
    }),

  createRobotFromImage: (image?: File, textHint?: string) => {
    const form = new FormData();
    if (image) form.append("image", image);
    if (textHint) form.append("text_hint", textHint);
    // Direct to backend - SSE cannot go through Next.js (it buffers)
    return fetch("https://nomi-api.zhuchao.life/api/robots/from-image", {
      method: "POST",
      body: form,
      credentials: "omit",
    });
  },

  listRobots: () => request<import("./types").Robot[]>("/api/robots"),

  getRobot: (id: string) =>
    request<import("./types").RobotDetail>(`/api/robots/${id}`),

  observeObject: (textDescription?: string, imageUrl?: string) =>
    request<import("./types").ObjectObservation>("/api/objects/observe", {
      method: "POST",
      body: JSON.stringify({
        text_description: textDescription,
        image_url: imageUrl,
      }),
    }),

  createConversation: () =>
    request<import("./types").Conversation>("/api/conversations", {
      method: "POST",
    }),

  sendMessage: (conversationId: string, content: string, model?: string, robotId?: string) => {
    let url = `/api/conversations/${conversationId}/message?model=${model || "deepseek-v4-flash"}`;
    if (robotId) url += `&robot_id=${robotId}`;
    return request<{ messages: import("./types").ChatMessage[]; timing: Record<string, unknown> }>(
      url, { method: "POST", body: JSON.stringify({ content }) }
    );
  },

  deleteRobot: (id: string) =>
    request<{ deleted: string; name: string }>(`/api/robots/${id}`, { method: "DELETE" }),

  listModels: () => request<{ id: string; label: string; provider: string }[]>("/api/conversations/models"),

  getMessages: (conversationId: string) =>
    request<import("./types").ChatMessage[]>(
      `/api/conversations/${conversationId}/messages`
    ),

  getLatestConversation: () =>
    request<{ id: string; messages: import("./types").ChatMessage[] } | null>(
      "/api/conversations/latest"
    ),

  startIdleChat: (topic?: string) => {
    return fetch("https://nomi-api.zhuchao.life/api/agents/idle-chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ topic }),
      credentials: "omit",
    });
  },
};
