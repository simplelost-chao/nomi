"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import type { ChatMessage, Robot } from "@/lib/types";

interface ModelOption {
  id: string;
  label: string;
  provider: string;
}

const AVATAR_COLORS = [
  "bg-nomi-rose-light",
  "bg-nomi-lavender-light",
  "bg-nomi-apricot-light",
  "bg-nomi-sage-light",
];
const AVATAR_GRADIENTS = [
  "from-nomi-rose to-nomi-apricot",
  "from-nomi-lavender to-nomi-rose-light",
  "from-nomi-apricot to-nomi-sage-light",
  "from-nomi-sage to-nomi-lavender",
];

type ActivityEvent = {
  id: string;
  type: "thought" | "message" | "skill_acquired" | "skill_used";
  robotId: string;
  robotName: string;
  content: string;
  extra?: string;
  timestamp: number;
};

const ACTIVITY_CONFIG: Record<ActivityEvent["type"], { icon: string; colorClass: string }> = {
  thought:       { icon: "💭", colorClass: "text-nomi-charcoal-soft" },
  message:       { icon: "💬", colorClass: "text-nomi-charcoal" },
  skill_acquired:{ icon: "✨", colorClass: "text-violet-600" },
  skill_used:    { icon: "⚡", colorClass: "text-indigo-500" },
};

function ChatPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const soloRobotId = searchParams.get("robot");

  const [robots, setRobots] = useState<Robot[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [models, setModels] = useState<ModelOption[]>([]);
  const [selectedModel, setSelectedModel] = useState("deepseek-v4-flash");
  const [voiceEnabled, setVoiceEnabled] = useState(true);
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [playingId, setPlayingId] = useState<string | null>(null);
  const [heartbeatAlive, setHeartbeatAlive] = useState(false);
  const [heartbeatInterval, setHeartbeatInterval] = useState(5);
  const [thoughts, setThoughts] = useState<{ robot_name: string; thought: string; timestamp: number }[]>([]);
  const [robotEnergy, setRobotEnergy] = useState<Record<string, number>>({});
  const [activityEvents, setActivityEvents] = useState<ActivityEvent[]>([]);
  const [selectedRobotIds, setSelectedRobotIds] = useState<Set<string>>(new Set());

  const lastSeq = useRef(0);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const activityEndRef = useRef<HTMLDivElement>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const audioElRef = useRef<HTMLAudioElement>(null);

  const senderIndexMap = useRef<Map<string, number>>(new Map());
  const getSenderIndex = (name: string | null) => {
    if (!name) return 0;
    if (!senderIndexMap.current.has(name)) {
      senderIndexMap.current.set(name, senderIndexMap.current.size);
    }
    return senderIndexMap.current.get(name) || 0;
  };

  // Select all robots by default when they load
  useEffect(() => {
    if (robots.length > 0 && selectedRobotIds.size === 0) {
      setSelectedRobotIds(new Set(
        soloRobotId ? [soloRobotId] : robots.map(r => r.id)
      ));
    }
  }, [robots, soloRobotId]);

  const toggleRobotSelection = useCallback((robotId: string) => {
    setSelectedRobotIds(prev => {
      const next = new Set(prev);
      if (next.has(robotId)) {
        if (next.size > 1) next.delete(robotId);
      } else {
        next.add(robotId);
      }
      return next;
    });
  }, []);

  const addActivity = useCallback((event: Omit<ActivityEvent, "id">) => {
    setActivityEvents(prev => [
      ...prev.slice(-100),
      { ...event, id: `act-${event.timestamp}-${Math.random().toString(36).slice(2)}` },
    ]);
  }, []);

  // Auto-scroll activity sidebar
  useEffect(() => {
    activityEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [activityEvents]);

  // Play TTS via the hidden <audio> element
  const playAudioBlob = useCallback(async (url: string, msgId: string): Promise<void> => {
    const audio = audioElRef.current;
    if (!audio) return;
    audio.pause();
    setPlayingId(msgId);
    return new Promise<void>((resolve) => {
      const done = () => { setPlayingId(null); resolve(); };
      audio.onended = done;
      audio.onerror = done;
      audio.src = url;
      audio.load();
      audio.play().catch(done);
    });
  }, []);

  const buildTTSUrl = (text: string, robotName: string, robotId?: string) => {
    let url = `/api/tts/speak?text=${encodeURIComponent(text)}&robot_name=${encodeURIComponent(robotName)}`;
    if (robotId) url += `&robot_id=${encodeURIComponent(robotId)}`;
    return url;
  };

  const [historyCount, setHistoryCount] = useState(0);

  useEffect(() => {
    api.listModels().then(setModels).catch(console.error);
    api.listRobots().then(setRobots).catch(console.error);
    fetch("/api/heartbeat/status").then(r => r.json()).then(d => { setHeartbeatAlive(d.alive); if (d.interval) setHeartbeatInterval(d.interval); }).catch(() => {});
    lastSeq.current = 0;

    // Load latest conversation history
    api.getLatestConversation().then(data => {
      if (data && data.messages.length > 0) {
        setConversationId(data.id);
        setMessages(data.messages);
        setHistoryCount(data.messages.length);
      }
    }).catch(() => {});
  }, []);

  // Heartbeat audio queue
  const heartbeatAudioQueue = useRef<{ text: string; name: string; id: string; robotId?: string }[]>([]);
  const isPlayingHeartbeat = useRef(false);
  const voiceEnabledRef = useRef(voiceEnabled);
  voiceEnabledRef.current = voiceEnabled;

  const signalBusy = useCallback(async (busy: boolean) => {
    try {
      await fetch(`/api/heartbeat/busy?busy=${busy}`, {
        method: "POST",
        signal: AbortSignal.timeout(3000),
      });
    } catch { /* non-critical */ }
  }, []);

  const processHeartbeatAudio = useCallback(async () => {
    if (isPlayingHeartbeat.current || !voiceEnabledRef.current) return;
    isPlayingHeartbeat.current = true;
    await signalBusy(true);
    while (heartbeatAudioQueue.current.length > 0) {
      const item = heartbeatAudioQueue.current.shift()!;
      // Add timestamp to bust any browser cache
      const url = buildTTSUrl(item.text, item.name, item.robotId) + `&_t=${Date.now()}`;
      await playAudioBlob(url, item.id);
    }
    await signalBusy(false);
    isPlayingHeartbeat.current = false;
  }, [signalBusy, playAudioBlob]);

  // Poll heartbeat events
  useEffect(() => {
    if (!heartbeatAlive) return;
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`/api/heartbeat/events?after=${lastSeq.current}&_t=${Date.now()}`, { cache: "no-store" });
        const data = await res.json();
        setHeartbeatAlive(data.alive);

        for (const event of data.events) {
          const seq = event.seq || 0;
          if (seq <= lastSeq.current) continue;
          lastSeq.current = seq;

          if (event.type === "thought") {
            setThoughts(prev => [...prev.slice(-10), {
              robot_name: event.robot_name,
              thought: event.thought,
              timestamp: event.timestamp,
            }]);
            if (event.energy !== undefined) {
              setRobotEnergy(prev => ({ ...prev, [event.robot_name]: event.energy }));
            }
            addActivity({
              type: "thought",
              robotId: event.robot_id,
              robotName: event.robot_name,
              content: event.thought,
              timestamp: event.timestamp,
            });
          } else if (event.type === "message") {
            const autoMsg: ChatMessage = {
              id: `hb-${event.seq}-${Math.random().toString(36).slice(2)}`,
              sender_type: "robot",
              sender_id: event.robot_id,
              sender_name: event.robot_name,
              content: event.target ? `@${event.target} ${event.content}` : event.content,
              emotion: null,
              created_at: new Date(event.timestamp * 1000).toISOString(),
              metadata: { model: "heartbeat" },
            };
            setMessages(prev => [...prev, autoMsg]);
            addActivity({
              type: "message",
              robotId: event.robot_id,
              robotName: event.robot_name,
              content: event.content,
              extra: event.target ? `→ ${event.target}` : undefined,
              timestamp: event.timestamp,
            });
            if (voiceEnabled && event.content) {
              // Immediately signal busy so backend pauses before next tick
              if (heartbeatAudioQueue.current.length === 0 && !isPlayingHeartbeat.current) {
                signalBusy(true);
              }
              heartbeatAudioQueue.current.push({
                text: event.content,
                name: event.robot_name,
                id: autoMsg.id,
                robotId: event.robot_id,
              });
              processHeartbeatAudio();
            }
          } else if (event.type === "system") {
            const sysMsg: ChatMessage = {
              id: `sys-${event.seq}-${Math.random().toString(36).slice(2)}`,
              sender_type: "system",
              sender_id: null,
              sender_name: null,
              content: event.message,
              emotion: null,
              created_at: new Date(event.timestamp * 1000).toISOString(),
            };
            setMessages(prev => [...prev, sysMsg]);
          } else if (event.type === "skill_acquired") {
            addActivity({
              type: "skill_acquired",
              robotId: event.robot_id,
              robotName: event.robot_name,
              content: event.skill_description || event.skill_name,
              extra: event.skill_name,
              timestamp: event.timestamp,
            });
          } else if (event.type === "skill_used") {
            addActivity({
              type: "skill_used",
              robotId: event.robot_id,
              robotName: event.robot_name,
              content: event.content || "",
              extra: event.skill_name,
              timestamp: event.timestamp,
            });
          }
        }
      } catch {}
    }, 2000);
    return () => clearInterval(interval);
  }, [heartbeatAlive, voiceEnabled, playAudioBlob, addActivity, processHeartbeatAudio]);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);
  useEffect(() => { scrollToBottom(); }, [messages, scrollToBottom]);

  const playTTS = useCallback((text: string, robotName: string, msgId: string, robotId?: string) => {
    playAudioBlob(buildTTSUrl(text, robotName, robotId), msgId);
  }, [playAudioBlob]);

  // Auto-play multiple messages in sequence (prefetch in parallel, play in order)
  const playAllInOrder = useCallback(async (items: { text: string; name: string; id: string; robotId?: string }[]) => {
    if (!voiceEnabled || items.length === 0) return;
    const fetchPromises = items.map(async (item) => {
      const url = buildTTSUrl(item.text, item.name, item.robotId);
      try {
        const res = await fetch(url);
        if (!res.ok) return null;
        const blob = await res.blob();
        return { ...item, blobUrl: URL.createObjectURL(blob) };
      } catch { return null; }
    });
    const results = await Promise.all(fetchPromises);
    for (const item of results) {
      if (!item) continue;
      await new Promise<void>((resolve) => {
        const audio = new Audio(item.blobUrl);
        audioRef.current = audio;
        setPlayingId(item.id);
        audio.onended = () => { setPlayingId(null); URL.revokeObjectURL(item.blobUrl); audioRef.current = null; resolve(); };
        audio.onerror = () => { setPlayingId(null); URL.revokeObjectURL(item.blobUrl); audioRef.current = null; resolve(); };
        audio.play().catch(() => { setPlayingId(null); resolve(); });
      });
    }
  }, [voiceEnabled]);

  // Voice recording
  const toggleRecording = useCallback(async () => {
    if (recording) {
      mediaRecorderRef.current?.stop();
      setRecording(false);
      return;
    }
    try {
      let stream: MediaStream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
      } catch {
        stream = await navigator.mediaDevices.getUserMedia({ audio: {} } as MediaStreamConstraints);
      }
      let mediaRecorder: MediaRecorder;
      try {
        mediaRecorder = new MediaRecorder(stream);
      } catch {
        mediaRecorder = new MediaRecorder(stream, { mimeType: "audio/mp4" });
      }
      chunksRef.current = [];
      mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data); };
      mediaRecorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunksRef.current);
        if (blob.size < 1000) return;
        setTranscribing(true);
        try {
          const ext = blob.type.includes("mp4") ? "m4a" : "webm";
          const form = new FormData();
          form.append("audio", blob, `recording.${ext}`);
          const res = await fetch("/api/stt/transcribe", { method: "POST", body: form });
          if (res.ok) {
            const data = await res.json();
            if (data.text) setInput((prev) => prev + data.text);
          }
        } catch (e) { console.error(e); }
        finally { setTranscribing(false); }
      };
      mediaRecorderRef.current = mediaRecorder;
      mediaRecorder.start();
      setRecording(true);
    } catch (e) {
      console.error("Mic error:", e);
      alert(`麦克风错误: ${e instanceof Error ? e.message : String(e)}`);
    }
  }, [recording]);

  // Unlock audio on first user interaction (Safari)
  const audioUnlocked = useRef(false);
  const unlockAudio = useCallback(() => {
    if (audioUnlocked.current) return;
    try {
      const ctx = new (window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext)();
      const buf = ctx.createBuffer(1, 1, 22050);
      const src = ctx.createBufferSource();
      src.buffer = buf;
      src.connect(ctx.destination);
      src.start(0);
      audioUnlocked.current = true;
    } catch {}
  }, []);

  const toggleHeartbeat = useCallback(async () => {
    unlockAudio();
    if (audioElRef.current) {
      audioElRef.current.src = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA=";
      audioElRef.current.play().catch(() => {});
    }
    if (heartbeatAlive) {
      await fetch("/api/heartbeat/sleep", { method: "POST" });
      setHeartbeatAlive(false);
    } else {
      lastSeq.current = 0;
      await fetch("/api/heartbeat/wake", { method: "POST" });
      setHeartbeatAlive(true);
    }
  }, [heartbeatAlive, unlockAudio]);

  const handleSend = async () => {
    if (!input.trim() || sending) return;
    unlockAudio();
    if (audioElRef.current) {
      audioElRef.current.src = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA=";
      audioElRef.current.play().catch(() => {});
    }

    // Auto-wake heartbeat if sleeping
    if (!heartbeatAlive) {
      lastSeq.current = 0;
      await fetch("/api/heartbeat/wake", { method: "POST" });
      setHeartbeatAlive(true);
    }

    let convId = conversationId;
    if (!convId) {
      const conv = await api.createConversation();
      convId = conv.id;
      setConversationId(convId);
    }
    const userText = input.trim();
    setInput("");
    setSending(true);

    const tempUserMsg: ChatMessage = {
      id: `temp-${Date.now()}`, sender_type: "user", sender_id: null,
      sender_name: "主人", content: userText, emotion: null,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, tempUserMsg]);

    try {
      const result = await api.sendMessage(convId, userText, selectedModel, soloRobotId || undefined);
      const robotMsgs = result.messages.filter((m: ChatMessage) => m.sender_type === "robot" && m.content);
      // Replace temp message with real user message, add all robot replies immediately
      setMessages((prev) => {
        const withoutTemp = prev.filter((m) => m.id !== tempUserMsg.id);
        return [...withoutTemp, ...result.messages];
      });
      // Play TTS in background — doesn't block input
      if (voiceEnabled && robotMsgs.length > 0) {
        playAllInOrder(robotMsgs.map((m: ChatMessage) => ({
          text: m.content!, name: m.sender_name || "", id: m.id, robotId: m.sender_id || undefined,
        })));
      }
    } catch (err) { console.error(err); }
    finally { setSending(false); }
  };

  const displayRobots = soloRobotId ? robots.filter(r => r.id === soloRobotId) : robots;
  const robotIndexMap = new Map(robots.map((r, i) => [r.id, i]));
  const filteredActivity = activityEvents.filter(e => selectedRobotIds.has(e.robotId));

  return (
    <div className="fixed inset-0 flex flex-col bg-nomi-warm-white">
      {/* ── Top bar ── */}
      <div className="z-10 glass-strong shadow-nomi shrink-0 px-3 pt-[env(safe-area-inset-top,8px)] pb-2 border-b border-nomi-rose-pale/30">
        <div className="flex items-center justify-between gap-2">
          {/* Left: back + clear */}
          <div className="flex items-center gap-3 shrink-0">
            <button
              onClick={() => router.push("/")}
              className="text-sm text-nomi-charcoal-muted hover:text-nomi-charcoal transition-colors"
            >
              ←
            </button>
            {messages.length > 0 && (
              <button
                onClick={() => {
                  if (confirm("清除所有对话？")) {
                    setMessages([]); setConversationId(null);
                    setThoughts([]); setActivityEvents([]);
                  }
                }}
                className="rounded-full bg-nomi-warm-gray/20 px-2 py-0.5 text-[11px] text-nomi-charcoal-muted active:bg-red-100 active:text-red-500"
              >
                清除
              </button>
            )}
          </div>

          {/* Center: robot avatars — mobile only */}
          <div className="flex md:hidden items-center gap-2 flex-1 justify-center overflow-x-auto">
            {displayRobots.map((r, i) => (
              <div key={r.id} className="flex flex-col items-center gap-0.5 shrink-0">
                <div className="relative">
                  <div className={`flex h-7 w-7 items-center justify-center rounded-full bg-gradient-to-br ${AVATAR_GRADIENTS[i % AVATAR_GRADIENTS.length]} text-xs font-semibold text-white shadow-sm`}>
                    {r.name.charAt(0)}
                  </div>
                  {heartbeatAlive && robotEnergy[r.name] !== undefined && (
                    <div className="absolute -bottom-0.5 left-0 right-0 mx-auto h-[3px] w-5 rounded-full bg-nomi-warm-gray/30 overflow-hidden">
                      <div className="h-full rounded-full transition-all duration-1000" style={{
                        width: `${robotEnergy[r.name]}%`,
                        backgroundColor: robotEnergy[r.name] > 50 ? "#86efac" : robotEnergy[r.name] > 20 ? "#fcd34d" : "#fca5a5",
                      }} />
                    </div>
                  )}
                </div>
                <span className="text-[9px] text-nomi-charcoal-muted">{r.name}</span>
              </div>
            ))}
          </div>

          {/* Right: controls */}
          <div className="flex items-center gap-2 shrink-0">
            <button
              onClick={toggleHeartbeat}
              className={`rounded-full px-2.5 py-1 text-[11px] font-medium transition-all ${heartbeatAlive ? "bg-green-100 text-green-700 shadow-sm" : "bg-nomi-warm-gray/20 text-nomi-charcoal-muted"}`}
              title={heartbeatAlive ? "小生命们正在活动" : "小生命们在沉睡"}
            >
              {heartbeatAlive ? "💚 醒着" : "💤 沉睡"}
            </button>
            <select
              value={heartbeatInterval}
              onChange={(e) => {
                const v = Number(e.target.value);
                setHeartbeatInterval(v);
                fetch(`/api/heartbeat/interval?seconds=${v}`, { method: "POST" }).catch(() => {});
              }}
              className="rounded-full bg-nomi-warm-gray/15 px-1.5 py-1 text-[10px] text-nomi-charcoal-muted focus:outline-none"
              title="心跳间隔"
            >
              {[1, 2, 3, 5, 8, 10, 15, 20, 30].map(s => (
                <option key={s} value={s}>{s}s</option>
              ))}
            </select>
            <button
              onClick={() => setVoiceEnabled(!voiceEnabled)}
              className={`rounded-full px-2 py-1 text-[11px] transition-colors ${voiceEnabled ? "bg-nomi-rose-light text-nomi-charcoal" : "bg-nomi-warm-gray/20 text-nomi-charcoal-muted"}`}
            >
              {voiceEnabled ? "🔊" : "🔇"}
            </button>
            <select
              value={selectedModel}
              onChange={(e) => setSelectedModel(e.target.value)}
              className="glass rounded-full px-2.5 py-1 text-[11px] text-nomi-charcoal-soft focus:outline-none"
            >
              {models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
            </select>
          </div>
        </div>
      </div>

      {/* ── Main content ── */}
      <div className="flex flex-1 min-h-0">

        {/* ── Left sidebar: per-robot windows (desktop only) ── */}
        <aside className="hidden md:flex w-64 lg:w-72 xl:w-80 flex-col border-r border-nomi-rose-pale/20 glass shrink-0 overflow-y-auto overscroll-contain">
          {!heartbeatAlive ? (
            <div className="flex flex-col items-center justify-center flex-1 gap-2 opacity-35 py-12">
              <div className="nomi-orb h-8 w-8" />
              <p className="text-[11px] text-nomi-charcoal-muted">小生命们在沉睡</p>
            </div>
          ) : (
            <div className="py-2 px-2 space-y-2">
              {displayRobots.map((r, i) => {
                const robotIdx = robotIndexMap.get(r.id) ?? i;
                const gradient = AVATAR_GRADIENTS[robotIdx % AVATAR_GRADIENTS.length];
                const energy = robotEnergy[r.name];
                const robotEvents = activityEvents.filter(e => e.robotId === r.id).slice(-40);
                const isSelected = selectedRobotIds.has(r.id);

                return (
                  <div
                    key={r.id}
                    className={`rounded-[14px] border transition-all ${
                      isSelected
                        ? "border-nomi-rose-light/40 shadow-nomi bg-white/60"
                        : "border-nomi-warm-gray/20 opacity-50 bg-white/30"
                    }`}
                  >
                    {/* Window header */}
                    <button
                      onClick={() => toggleRobotSelection(r.id)}
                      className="flex w-full items-center gap-2 px-3 py-2 rounded-t-[14px] hover:bg-nomi-warm-gray/10 transition-colors"
                    >
                      {/* Avatar */}
                      <div className={`w-6 h-6 rounded-full bg-gradient-to-br ${gradient} flex items-center justify-center text-[9px] font-bold text-white shrink-0`}>
                        {r.name.charAt(0)}
                      </div>
                      {/* Name */}
                      <span className="text-[12px] font-medium text-nomi-charcoal flex-1 text-left">{r.name}</span>
                      {/* Selection dot */}
                      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${isSelected ? "bg-green-400" : "bg-nomi-warm-gray/40"}`} />
                    </button>

                    {/* Energy bar */}
                    {energy !== undefined && (
                      <div className="px-3 pb-1.5">
                        <div className="flex items-center gap-1.5">
                          <div className="flex-1 h-1 rounded-full bg-nomi-warm-gray/20 overflow-hidden">
                            <div
                              className="h-full rounded-full transition-all duration-1000"
                              style={{
                                width: `${energy}%`,
                                backgroundColor: energy > 60 ? "#86efac" : energy > 25 ? "#fcd34d" : "#fca5a5",
                              }}
                            />
                          </div>
                          <span className="text-[9px] text-nomi-charcoal-muted shrink-0 tabular-nums">{Math.round(energy)}%</span>
                        </div>
                      </div>
                    )}

                    {/* Activity feed */}
                    {isSelected && (
                      <div className="max-h-48 overflow-y-auto overscroll-contain border-t border-nomi-warm-gray/10">
                        {robotEvents.length === 0 ? (
                          <p className="px-3 py-3 text-[10px] text-nomi-charcoal-muted opacity-50 text-center">等待活动...</p>
                        ) : (
                          <div className="py-1.5">
                            {robotEvents.map((event) => {
                              const cfg = ACTIVITY_CONFIG[event.type];
                              return (
                                <div key={event.id} className="flex gap-1.5 px-3 py-1 hover:bg-nomi-warm-gray/10 transition-colors">
                                  <span className="text-[10px] shrink-0 mt-0.5">{cfg.icon}</span>
                                  <div className="min-w-0">
                                    {event.extra && (
                                      <span className="text-[9px] text-nomi-charcoal-muted/60 block truncate">{event.extra}</span>
                                    )}
                                    <p className={`text-[11px] leading-relaxed ${cfg.colorClass} line-clamp-2`}>
                                      {event.content}
                                    </p>
                                  </div>
                                </div>
                              );
                            })}
                            <div ref={activityEndRef} />
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </aside>

        {/* ── Chat area ── */}
        <div className="flex flex-1 flex-col min-h-0">

          {/* Messages — scrollable */}
          <div
            className="flex-1 min-h-0 overflow-y-auto overscroll-contain"
            style={{ WebkitOverflowScrolling: "touch" }}
          >
            <div className="mx-auto max-w-lg px-4 py-4">
              <div className="space-y-3">
                {/* Character portrait - show when idle or at top */}
                {displayRobots.length === 1 && (
                  <div className="flex flex-col items-center pb-2">
                    <img
                      src={`/api/admin/characters/${displayRobots[0].id}/image/${sending ? 'thinking' : 'idle'}?t=${Date.now()}`}
                      alt={displayRobots[0].name}
                      className="h-48 md:h-56 object-contain drop-shadow-lg transition-all duration-500"
                      onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                    />
                    <p className="text-xs text-nomi-charcoal-muted mt-1">{displayRobots[0].name}</p>
                  </div>
                )}

                {messages.length === 0 && !sending && displayRobots.length !== 1 && (
                  <div className="flex flex-col items-center justify-center py-20 gap-3">
                    <div className="nomi-orb h-12 w-12" />
                    <p className="text-sm text-nomi-charcoal-muted">和小生命们聊聊天</p>
                  </div>
                )}

                {messages.map((msg, msgIndex) => {
                  // Divider between history and new messages
                  const showDivider = historyCount > 0 && msgIndex === historyCount;
                  const divider = showDivider ? (
                    <div key="__history_divider__" className="flex items-center gap-3 py-2">
                      <div className="flex-1 h-px bg-nomi-warm-gray/30" />
                      <span className="text-[10px] text-nomi-charcoal-muted whitespace-nowrap">以上是历史消息</span>
                      <div className="flex-1 h-px bg-nomi-warm-gray/30" />
                    </div>
                  ) : null;
                  if (msg.sender_type === "system") {
                    return (
                      <>{divider}<div key={msg.id} className="text-center">
                        <span className="text-[11px] text-nomi-charcoal-muted">{msg.content}</span>
                      </div></>
                    );
                  }

                  const isUser = msg.sender_type === "user";
                  const avatarColor = isUser
                    ? "bg-nomi-apricot"
                    : AVATAR_COLORS[getSenderIndex(msg.sender_name) % AVATAR_COLORS.length];
                  const initial = (msg.sender_name || "?").charAt(0);
                  const isPlaying = playingId === msg.id;
                  const senderRobot = !isUser ? robots.find(r => r.id === msg.sender_id || r.name === msg.sender_name) : null;
                  const avatarUrl = senderRobot?.voice_profile?.avatar || (senderRobot ? `/api/admin/characters/${senderRobot.id}/image/idle` : undefined);

                  return (
                    <>{divider}<div key={msg.id} className={`flex gap-2.5 ${isUser ? "flex-row-reverse" : ""}`}>
                      {avatarUrl ? (
                        <img src={avatarUrl} alt={msg.sender_name || ""} className="h-8 w-8 shrink-0 rounded-full object-cover shadow-sm bg-white/50" />
                      ) : (
                        <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${avatarColor} text-xs font-semibold text-nomi-charcoal`}>
                          {initial}
                        </div>
                      )}
                      <div className={`max-w-[75%] flex flex-col ${isUser ? "items-end" : "items-start"}`}>
                        {!isUser && <p className="mb-0.5 text-[11px] text-nomi-charcoal-muted">{msg.sender_name}</p>}
                        <div className={`rounded-[16px] px-3.5 py-2.5 text-[13px] leading-relaxed ${isUser ? "glass-strong" : "glass"} shadow-nomi`}>
                          {msg.content}
                        </div>
                        {!isUser && msg.content && (
                          <div className="mt-0.5 flex items-center gap-2 text-[10px] text-nomi-charcoal-muted">
                            {msg.metadata?.llm_time_ms && <span>{(msg.metadata.llm_time_ms / 1000).toFixed(1)}s</span>}
                            {msg.metadata?.model && <span>{msg.metadata.model}</span>}
                            <button
                              onClick={() => playTTS(msg.content!, msg.sender_name || "", msg.id, msg.sender_id || undefined)}
                              className={`transition-colors ${isPlaying ? "text-nomi-rose" : "hover:text-nomi-charcoal"}`}
                            >
                              {isPlaying ? "⏸" : "▶"}
                            </button>
                          </div>
                        )}
                      </div>
                    </div></>
                  );
                })}

                {sending && (
                  <div className="flex gap-2.5">
                    <div className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${AVATAR_COLORS[0]}`}>
                      <div className="nomi-orb h-4 w-4" />
                    </div>
                    <div className="glass shadow-nomi rounded-[16px] px-4 py-3">
                      <div className="flex items-center gap-1">
                        <span className="inline-block h-1.5 w-1.5 animate-bounce rounded-full bg-nomi-charcoal-muted [animation-delay:0ms]" />
                        <span className="inline-block h-1.5 w-1.5 animate-bounce rounded-full bg-nomi-charcoal-muted [animation-delay:150ms]" />
                        <span className="inline-block h-1.5 w-1.5 animate-bounce rounded-full bg-nomi-charcoal-muted [animation-delay:300ms]" />
                      </div>
                    </div>
                  </div>
                )}

                {/* Inline thoughts — mobile only (on desktop they appear in sidebar) */}
                {heartbeatAlive && thoughts.length > 0 && (
                  <div className="md:hidden space-y-1.5 py-2">
                    {thoughts.slice(-3).map((t, i) => (
                      <div key={i} className="flex items-center gap-2 animate-fade-up" style={{ opacity: 0.5 + i * 0.15 }}>
                        <span className="text-[10px] text-nomi-charcoal-muted">{t.robot_name}</span>
                        <span className="text-[11px] italic text-nomi-charcoal-muted">💭 {t.thought}</span>
                      </div>
                    ))}
                  </div>
                )}

                <div ref={messagesEndRef} />
              </div>
            </div>
          </div>

          {/* Heartbeat pulse indicator */}
          {heartbeatAlive && (
            <div className="flex items-center justify-center py-1.5">
              <div className="flex items-center gap-2">
                <div className="relative flex items-center justify-center">
                  {/* Ripple ring */}
                  <div
                    className="absolute h-8 w-8 rounded-full bg-nomi-rose/20"
                    style={{ animation: `heartbeat-ripple ${heartbeatInterval}s ease-out infinite` }}
                  />
                  {/* Heart icon */}
                  <div
                    className="relative z-10 text-base text-nomi-rose"
                    style={{ animation: `heartbeat-pump ${heartbeatInterval}s ease-in-out infinite` }}
                  >
                    ♥
                  </div>
                </div>
                <span className="text-[10px] text-nomi-charcoal-muted/50 font-light tracking-wider">alive</span>
              </div>
            </div>
          )}

          {/* Input bar */}
          <div className="z-10 glass-strong shrink-0 border-t border-nomi-rose-pale/30 px-3 pt-2 pb-[max(env(safe-area-inset-bottom),8px)]">
            <div className="mx-auto max-w-lg flex gap-2">
              <button
                onClick={toggleRecording}
                disabled={transcribing}
                className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full transition-all ${
                  recording
                    ? "bg-red-400 text-white scale-110 animate-pulse"
                    : transcribing
                    ? "bg-nomi-warm-gray/30 text-nomi-charcoal-muted"
                    : "glass text-nomi-charcoal-muted hover:text-nomi-charcoal"
                }`}
              >
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 18.75a6 6 0 006-6v-1.5m-6 7.5a6 6 0 01-6-6v-1.5m6 7.5v3.75m-3.75 0h7.5M12 15.75a3 3 0 01-3-3V4.5a3 3 0 116 0v8.25a3 3 0 01-3 3z" />
                </svg>
              </button>
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleSend()}
                placeholder={recording ? "正在录音..." : transcribing ? "识别中..." : "说点什么..."}
                disabled={sending}
                className="glass flex-1 rounded-full px-4 py-2.5 text-sm placeholder:text-nomi-charcoal-muted focus:outline-none focus:ring-1 focus:ring-nomi-rose-light disabled:opacity-50"
              />
              <button
                onClick={handleSend}
                disabled={!input.trim() || sending}
                className="rounded-full bg-gradient-to-r from-nomi-rose to-nomi-apricot px-5 py-2.5 text-sm font-medium text-white shadow-nomi disabled:opacity-40"
              >
                发送
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Hidden audio element — must be in DOM for Safari */}
      <audio ref={audioElRef} playsInline style={{ display: "none" }} suppressHydrationWarning />
    </div>
  );
}

export default function ChatPage() {
  return (
    <Suspense fallback={<div className="flex h-[100dvh] items-center justify-center"><div className="nomi-orb h-10 w-10" /></div>}>
      <ChatPageInner />
    </Suspense>
  );
}
