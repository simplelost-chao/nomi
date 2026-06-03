"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import type { ChatMessage, Robot } from "@/lib/types";

const ROBOT_TTS_LANG: Record<string, "japanese" | "chinese"> = {
  "フリーレン": "japanese",
  "冯宝宝": "chinese",
};

const ROBOT_VOICE_MAP: Record<string, string> = {
  "フリーレン": "frieren",
  "冯宝宝": "fengbaobao",
};

function parseBotReply(raw: string) {
  const emotionMatch = raw.match(/\[emotion:(\w+)\]/);
  const emotion = emotionMatch?.[1] || "Normal";
  const chineseMatch = raw.match(/中文[：:]\s*(.+)/);
  const japaneseMatch = raw.match(/日本語[：:]\s*(.+)/);
  const chinese = chineseMatch?.[1]?.trim() || raw.replace(/\[emotion:\w+\]/, "").trim();
  const japanese = japaneseMatch?.[1]?.trim() || "";
  return { emotion, chinese, japanese };
}

function ChatInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const robotIdParam = searchParams.get("robot");

  const [robots, setRobots] = useState<Robot[]>([]);
  const [robot, setRobot] = useState<Robot | null>(null);
  const [messages, setMessages] = useState<{ id: string; role: "user" | "bot"; text: string; japanese?: string; emotion?: string; time: string }[]>([]);
  const [input, setInput] = useState("");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [playingId, setPlayingId] = useState<string | null>(null);
  const [showPicker, setShowPicker] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Load robots
  useEffect(() => {
    api.listRobots().then((list) => {
      setRobots(list);
      const target = robotIdParam ? list.find(r => r.id === robotIdParam) : list[0];
      if (target) setRobot(target);
    }).catch(console.error);
  }, [robotIdParam]);

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, sending]);

  const switchRobot = useCallback((r: Robot) => {
    setRobot(r);
    setMessages([]);
    setConversationId(null);
    setShowPicker(false);
  }, []);

  // Unlock audio on first user interaction (required for iOS Safari)
  const audioUnlocked = useRef(false);
  const unlockAudio = useCallback(() => {
    if (audioUnlocked.current || !audioRef.current) return;
    const a = audioRef.current;
    a.src = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA=";
    a.play().then(() => { audioUnlocked.current = true; }).catch(() => {});
  }, []);

  // TTS — fetch full audio and play
  const playTTS = useCallback(async (text: string, msgId: string) => {
    if (!robot || !audioRef.current) return;
    const character = ROBOT_VOICE_MAP[robot.name] || "frieren";
    const url = `/api/tts/speak-genie?text=${encodeURIComponent(text)}&character=${encodeURIComponent(character)}&emotion=Normal`;

    setPlayingId(msgId);
    try {
      const res = await fetch(url);
      if (!res.ok) { setPlayingId(null); return; }
      const blob = await res.blob();
      if (blob.size < 500) { setPlayingId(null); return; }
      const blobUrl = URL.createObjectURL(blob);
      const audio = audioRef.current!;
      audio.pause();
      audio.src = blobUrl;
      audio.onended = () => { setPlayingId(null); URL.revokeObjectURL(blobUrl); };
      audio.onerror = () => { setPlayingId(null); URL.revokeObjectURL(blobUrl); };
      await audio.play();
    } catch {
      setPlayingId(null);
    }
  }, [robot]);

  // Send message
  const handleSend = async () => {
    if (!input.trim() || sending || !robot) return;
    unlockAudio();

    const text = input.trim();
    setInput("");
    setSending(true);

    const userMsg = { id: `u-${Date.now()}`, role: "user" as const, text, time: new Date().toISOString() };
    setMessages(prev => [...prev, userMsg]);

    try {
      let convId = conversationId;
      if (!convId) {
        const conv = await api.createConversation();
        convId = conv.id;
        setConversationId(convId);
      }

      const result = await api.sendMessage(convId, text, "deepseek-v4-flash", robot.id);
      const botReplies = result.messages.filter(m => m.sender_type !== "user" && m.content);

      const newMsgs = botReplies.map(m => {
        const parsed = parseBotReply(m.content!);
        return {
          id: m.id,
          role: "bot" as const,
          text: parsed.chinese,
          japanese: parsed.japanese,
          emotion: parsed.emotion,
          time: m.created_at,
        };
      });
      setMessages(prev => [...prev, ...newMsgs]);

      // Auto-play TTS in background — don't block sending
      if (newMsgs.length > 0) {
        const msg = newMsgs[0];
        const ttsLang = ROBOT_TTS_LANG[robot.name] || "japanese";
        const ttsText = ttsLang === "japanese" && msg.japanese ? msg.japanese : msg.text;
        if (ttsText) {
          playTTS(ttsText, msg.id); // fire and forget, don't await
        }
      }
    } catch (err) {
      console.error("Send failed:", err);
    } finally {
      setSending(false);
      inputRef.current?.focus();
    }
  };

  const characterState = sending ? "thinking" : "idle";
  const portraitUrl = robot ? `/api/admin/characters/${robot.id}/image/${characterState}` : null;

  return (
    <div className="fixed inset-0 flex flex-col bg-nomi-cream">
      <div className="nomi-bg-glow" />
      <div className="nomi-bg-glow-2" />

      {/* Top bar */}
      <div className="z-10 glass-strong shadow-nomi shrink-0 px-4 pt-[env(safe-area-inset-top,8px)] pb-2 border-b border-nomi-rose-pale/30">
        <div className="flex items-center justify-between">
          <button onClick={() => router.push("/")} className="text-sm text-nomi-charcoal-muted hover:text-nomi-charcoal">←</button>

          {/* Character selector */}
          <button onClick={() => setShowPicker(!showPicker)} className="flex items-center gap-2">
            {robot && portraitUrl && (
              <img src={`/api/admin/characters/${robot.id}/image/idle`} alt="" className="h-7 w-7 rounded-full object-cover bg-white/50" />
            )}
            <span className="text-sm font-medium text-nomi-charcoal">{robot?.name || "选择角色"}</span>
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="6 9 12 15 18 9" /></svg>
          </button>

          <button onClick={() => router.push("/group-chat")} className="text-[11px] text-nomi-charcoal-muted hover:text-nomi-charcoal bg-nomi-warm-gray/20 rounded-full px-2.5 py-1">
            群聊
          </button>
        </div>

        {/* Character picker dropdown */}
        {showPicker && (
          <div className="mt-2 space-y-1">
            {robots.map(r => (
              <button
                key={r.id}
                onClick={() => switchRobot(r)}
                className={`w-full flex items-center gap-3 px-3 py-2 rounded-xl transition-all ${
                  robot?.id === r.id ? "bg-nomi-rose-pale/50 shadow-sm" : "hover:bg-white/50"
                }`}
              >
                <img
                  src={`/api/admin/characters/${r.id}/image/idle`}
                  alt={r.name}
                  className="h-9 w-9 rounded-full object-cover bg-white/50"
                  onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                />
                <div className="text-left">
                  <p className="text-sm font-medium text-nomi-charcoal">{r.name}</p>
                  <p className="text-[10px] text-nomi-charcoal-muted">{r.current_status || "在线"}</p>
                </div>
                {robot?.id === r.id && <div className="ml-auto w-2 h-2 rounded-full bg-green-400" />}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Chat area */}
      <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain" style={{ WebkitOverflowScrolling: "touch" }}>
        <div className="mx-auto max-w-lg px-4 py-4">
          {/* Character portrait */}
          {robot && portraitUrl && (
            <div className="flex flex-col items-center pb-4">
              <img
                src={`${portraitUrl}?t=1`}
                alt={robot.name}
                className="h-52 md:h-64 object-contain drop-shadow-lg transition-all duration-500"
                onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
              />
            </div>
          )}

          {/* Messages */}
          <div className="space-y-4">
            {messages.length === 0 && !sending && robot && (
              <div className="text-center py-8">
                <p className="text-sm text-nomi-charcoal-muted">和 {robot.name} 说说话吧</p>
              </div>
            )}

            {messages.map(msg => {
              const isUser = msg.role === "user";
              const isPlaying = playingId === msg.id;

              return (
                <div key={msg.id} className={`flex gap-3 ${isUser ? "flex-row-reverse" : ""} animate-fade-up`}>
                  {!isUser && robot && (
                    <img
                      src={`/api/admin/characters/${robot.id}/image/idle`}
                      alt={robot.name}
                      className="h-8 w-8 shrink-0 rounded-full object-cover bg-white/50 shadow-sm"
                    />
                  )}
                  {isUser && (
                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-nomi-apricot text-xs font-semibold text-nomi-charcoal">
                      我
                    </div>
                  )}
                  <div className={`max-w-[78%] flex flex-col ${isUser ? "items-end" : "items-start"}`}>
                    <div className={`rounded-2xl px-4 py-3 text-[14px] leading-relaxed shadow-nomi ${
                      isUser ? "glass-strong" : "glass"
                    }`}>
                      {msg.text}
                    </div>
                    {!isUser && msg.text && (
                      <div className="mt-1 flex items-center gap-3 px-1">
                        <button
                          onClick={() => {
                            const ttsLang = robot ? (ROBOT_TTS_LANG[robot.name] || "japanese") : "japanese";
                            const ttsText = ttsLang === "japanese" && msg.japanese ? msg.japanese : msg.text;
                            playTTS(ttsText, msg.id);
                          }}
                          className={`text-[11px] transition-colors ${isPlaying ? "text-nomi-rose" : "text-nomi-charcoal-muted hover:text-nomi-charcoal"}`}
                        >
                          {isPlaying ? "⏸ 播放中" : "▶ 播放"}
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}

            {sending && (
              <div className="flex gap-3">
                {robot && (
                  <img
                    src={`/api/admin/characters/${robot.id}/image/thinking`}
                    alt=""
                    className="h-8 w-8 shrink-0 rounded-full object-cover bg-white/50 shadow-sm"
                  />
                )}
                <div className="glass shadow-nomi rounded-2xl px-4 py-3">
                  <div className="flex items-center gap-1">
                    <span className="inline-block h-1.5 w-1.5 animate-bounce rounded-full bg-nomi-charcoal-muted [animation-delay:0ms]" />
                    <span className="inline-block h-1.5 w-1.5 animate-bounce rounded-full bg-nomi-charcoal-muted [animation-delay:150ms]" />
                    <span className="inline-block h-1.5 w-1.5 animate-bounce rounded-full bg-nomi-charcoal-muted [animation-delay:300ms]" />
                  </div>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>
        </div>
      </div>

      {/* Input bar */}
      <div className="z-10 glass-strong shrink-0 border-t border-nomi-rose-pale/30 px-4 pt-2 pb-[max(env(safe-area-inset-bottom),8px)]">
        <div className="mx-auto max-w-lg flex gap-2">
          <input
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                handleSend();
              }
            }}
            placeholder={`和${robot?.name || "角色"}说点什么...`}
            disabled={sending || !robot}
            autoFocus
            className="glass flex-1 rounded-full px-4 py-2.5 text-[16px] placeholder:text-nomi-charcoal-muted focus:outline-none focus:ring-1 focus:ring-nomi-rose-light disabled:opacity-50"
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || sending || !robot}
            className="rounded-full bg-gradient-to-r from-nomi-rose to-nomi-apricot px-5 py-2.5 text-sm font-medium text-white shadow-nomi disabled:opacity-40 active:scale-95 transition-transform"
          >
            发送
          </button>
        </div>
      </div>

      <audio ref={audioRef} playsInline style={{ display: "none" }} />
    </div>
  );
}

export default function ChatPage() {
  return (
    <Suspense fallback={<div className="flex items-center justify-center h-screen"><div className="nomi-orb h-12 w-12" /></div>}>
      <ChatInner />
    </Suspense>
  );
}
