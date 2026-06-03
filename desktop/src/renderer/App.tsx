import { useCallback, useEffect, useRef, useState } from "react";
import type { CharacterState } from "./components/Avatar";
import { AvatarSwitch, getStoredMode, storeMode, type DisplayMode } from "./components/AvatarSwitch";
import { startLipSync, stopLipSync } from "./components/Live2DAvatar";
import { ChatPanel } from "./components/ChatPanel";
import { LoadingScreen } from "./components/LoadingScreen";
import { AgentSettings } from "./components/AgentSettings";
import { VoiceButton } from "./components/VoiceButton";
import { api } from "./api";
import type { ChatMessage, Robot } from "./types";
import { CHARACTER_DIRS, CHARACTER_LIVE2D, ROBOT_TTS_LANG } from "./types";

declare global {
  interface Window {
    nomi: {
      toggleExpand: () => void;
      minimize: () => void;
      getBackendStatus: () => Promise<boolean>;
      onBackendReady: (callback: () => void) => () => void;
      agent: {
        getConfig: () => Promise<Record<string, unknown>>;
        updateConfig: (partial: Record<string, unknown>) => Promise<Record<string, unknown>>;
        getStatus: () => Promise<string>;
        start: () => Promise<void>;
        stop: () => Promise<void>;
        onReaction: (callback: (data: { text: string; text_ja: string; emotion: string; type: string }) => void) => () => void;
        onStatus: (callback: (data: { status: string }) => void) => () => void;
        onActionResult: (callback: (data: { type: string; success: boolean; result?: string }) => void) => () => void;
        executeAction: (action: { type: string; params: Record<string, string> }) => Promise<{ type: string; success: boolean; result?: string }>;
        getDesktopContext: () => Promise<{ activeApp: string; windowTitle: string; screenDescription: string }>;
      };
    };
  }
}

// Per-robot chat state
interface RobotChat {
  conversationId: string | null;
  messages: ChatMessage[];
}

export default function App() {
  const [backendReady, setBackendReady] = useState(false);
  const [showChat, setShowChat] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [robots, setRobots] = useState<Robot[]>([]);
  const [robot, setRobot] = useState<Robot | null>(null);
  const [characterState, setCharacterState] = useState<CharacterState>("idle");
  const [isWaiting, setIsWaiting] = useState(false);
  const [showAgentSettings, setShowAgentSettings] = useState(false);
  const [agentStatus, setAgentStatus] = useState<string>("idle");
  const [voiceEnabled, setVoiceEnabled] = useState(true);
  const [displayMode, setDisplayMode] = useState<DisplayMode>("2d");
  const [heartbeatOn, setHeartbeatOn] = useState(() => {
    try { return localStorage.getItem("nomi-heartbeat") === "true"; } catch { return false; }
  });
  const [heartbeatInterval, setHeartbeatIntervalState] = useState(() => {
    try { return parseInt(localStorage.getItem("nomi-heartbeat-interval") || "10"); } catch { return 10; }
  });
  const heartbeatBusy = useRef(false);

  // Load voice config on mount and keep in sync
  useEffect(() => {
    if (!window.nomi?.agent) return;
    window.nomi.agent.getConfig().then((c: any) => setVoiceEnabled(c?.voice?.enabled ?? true));
  }, [showAgentSettings]); // re-read when settings panel closes

  // Floating subtitle
  const [subtitle, setSubtitle] = useState("");
  const subtitleTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  function showSubtitle(text: string) {
    setSubtitle(text);
    if (subtitleTimer.current) clearTimeout(subtitleTimer.current);
    subtitleTimer.current = setTimeout(() => setSubtitle(""), 8000);
  }

  /** Play a TTS blob with lip-sync */
  const playTtsBlob = useCallback(async (blob: Blob) => {
    const audioUrl = URL.createObjectURL(blob);
    const audio = new Audio(audioUrl);
    startLipSync(audio);

    return new Promise<void>((resolve, reject) => {
      audio.onended = () => { URL.revokeObjectURL(audioUrl); stopLipSync(); resolve(); };
      audio.onerror = (e) => { URL.revokeObjectURL(audioUrl); stopLipSync(); reject(e); };
      audio.play().catch((e) => { stopLipSync(); reject(e); });
    });
  }, []);

  /** Play TTS with lip-sync (fetch + play) */
  const playTts = useCallback(async (text: string, robotName: string, emotion: string) => {
    const blob = await api.fetchTtsBlob(text, robotName, emotion);
    if (!blob) return;

    const audioUrl = URL.createObjectURL(blob);
    const audio = new Audio(audioUrl);
    startLipSync(audio);

    return new Promise<void>((resolve, reject) => {
      audio.onended = () => {
        URL.revokeObjectURL(audioUrl);
        stopLipSync();
        resolve();
      };
      audio.onerror = (e) => {
        URL.revokeObjectURL(audioUrl);
        stopLipSync();
        reject(e);
      };
      audio.play().catch((e) => {
        stopLipSync();
        reject(e);
      });
    });
  }, []);

  // Store chat history per robot
  const chatMap = useRef<Map<string, RobotChat>>(new Map());

  function getChatState(): RobotChat {
    if (!robot) return { conversationId: null, messages: [] };
    if (!chatMap.current.has(robot.id)) {
      chatMap.current.set(robot.id, { conversationId: null, messages: [] });
    }
    return chatMap.current.get(robot.id)!;
  }

  function updateChatState(update: Partial<RobotChat>) {
    if (!robot) return;
    const current = getChatState();
    chatMap.current.set(robot.id, { ...current, ...update });
  }

  // Force re-render when messages change
  const [msgVersion, setMsgVersion] = useState(0);

  useEffect(() => {
    if (!window.nomi) {
      setBackendReady(true);
      return;
    }

    window.nomi.getBackendStatus().then((ready) => {
      if (ready) setBackendReady(true);
    });

    const cleanup = window.nomi.onBackendReady(() => {
      setBackendReady(true);
    });
    return cleanup;
  }, []);

  useEffect(() => {
    if (!backendReady) return;

    api.listRobots().then((allRobots) => {
      setRobots(allRobots);
      if (allRobots.length > 0 && !robot) {
        const frieren = allRobots.find((r) => r.name === "フリーレン");
        setRobot(frieren || allRobots[0]);
      }
    }).catch(() => {});
  }, [backendReady]);

  // Agent reaction listener
  useEffect(() => {
    if (!window.nomi?.agent) return;

    const cleanupReaction = window.nomi.agent.onReaction((data) => {
      const reactionMsg: ChatMessage = {
        id: `reaction-${Date.now()}`,
        sender_type: "robot",
        sender_id: robot?.id || null,
        sender_name: robot?.name || "Agent",
        content: data.text,
        emotion: null,
        created_at: new Date().toISOString(),
        _japanese: data.text_ja,
        _emotion: data.emotion,
        _isReaction: true,
      };
      if (robot) {
        const current = getChatState();
        updateChatState({ messages: [...current.messages, reactionMsg] });
        setMsgVersion((v) => v + 1);
      }

      showSubtitle(data.text);

      const emotionState = data.emotion === "Sad" ? "sad"
        : data.emotion === "Surprised" ? "surprised"
        : data.emotion === "Happy" ? "happy"
        : "speaking";
      setCharacterState(emotionState as CharacterState);

      if (voiceEnabled && data.text_ja) {
        playTts(data.text_ja, robot?.name || "", data.emotion || "Normal")
          .catch(console.error)
          .finally(() => setCharacterState("idle"));
      } else {
        setTimeout(() => setCharacterState("idle"), 3000);
      }
    });

    const cleanupStatus = window.nomi.agent.onStatus((data) => {
      setAgentStatus(data.status);
    });

    return () => { cleanupReaction(); cleanupStatus(); };
  }, [robot]);

  // Sync displayMode and live2dScale when robot changes
  useEffect(() => {
    if (robot && CHARACTER_LIVE2D[robot.name]) {
      setDisplayMode(getStoredMode(robot.name));
    } else {
      setDisplayMode("2d");
    }
  }, [robot]);

  // Heartbeat timer
  useEffect(() => {
    if (!heartbeatOn || !robot) return;

    const tick = async () => {
      console.log("[heartbeat] tick, busy:", heartbeatBusy.current, "waiting:", isWaiting);
      if (heartbeatBusy.current) return;
      heartbeatBusy.current = true;

      try {
        // Capture screen
        let screenDesc = "";
        let activeApp = "";
        let windowTitle = "";
        try {
          if (window.nomi?.agent?.getDesktopContext) {
            const ctx = await window.nomi.agent.getDesktopContext();
            activeApp = ctx.activeApp;
            windowTitle = ctx.windowTitle;
            screenDesc = ctx.screenDescription || "";
          }
        } catch {}

        console.log("[heartbeat] screen:", screenDesc?.slice(0, 50), "app:", activeApp);
        if (!screenDesc && !activeApp) { console.log("[heartbeat] no context, skip"); heartbeatBusy.current = false; return; }

        // Let AI decide whether to react
        setCharacterState("thinking");
        const result = await api.agentReact(
          screenDesc || `${activeApp} - ${windowTitle}`,
          "心跳观察：根据屏幕内容和记忆，决定是否要主动说话。如果没有特别值得评论的内容，回复空字符串。",
          robot.id,
          { active_app: activeApp, window_title: windowTitle }
        );

        if (result.reaction && result.reaction.trim()) {
          // Has something to say
          const reactMsg: ChatMessage = {
            id: `heartbeat-${Date.now()}`,
            sender_type: "robot",
            sender_id: robot.id,
            sender_name: robot.name,
            content: result.reaction,
            emotion: null,
            created_at: new Date().toISOString(),
            _japanese: result.reaction_ja,
            _emotion: result.emotion,
            _isReaction: true,
          };
          const current = getChatState().messages;
          updateChatState({ messages: [...current, reactMsg] });
          setMsgVersion((v) => v + 1);

          const emotionState = result.emotion === "Sad" ? "sad"
            : result.emotion === "Surprised" ? "surprised"
            : result.emotion === "Happy" ? "happy"
            : "speaking";
          setCharacterState(emotionState as CharacterState);

          if (voiceEnabled && result.reaction_ja) {
            try {
              const blob = await api.fetchTtsBlob(result.reaction_ja, robot.name, result.emotion || "Normal");
              if (blob) {
                // Show subtitle when TTS starts playing (synced)
                showSubtitle(result.reaction);
                setCharacterState(emotionState as CharacterState);
                await playTtsBlob(blob);
              }
            } catch (e) {
              console.error("Heartbeat TTS failed:", e);
              showSubtitle(result.reaction);
            }
          } else {
            showSubtitle(result.reaction);
            await new Promise(r => setTimeout(r, 3000));
          }
        }

        setCharacterState("idle");
      } catch (err) {
        console.error("Heartbeat error:", err);
        setCharacterState("idle");
      } finally {
        heartbeatBusy.current = false;
      }
    };

    const id = setInterval(tick, heartbeatInterval * 1000);
    return () => clearInterval(id);
  }, [heartbeatOn, heartbeatInterval, robot, voiceEnabled]);

  const toggleHeartbeat = useCallback(() => {
    const next = !heartbeatOn;
    setHeartbeatOn(next);
    try { localStorage.setItem("nomi-heartbeat", String(next)); } catch {}
  }, [heartbeatOn]);

  const toggleDisplayMode = useCallback(() => {
    if (!robot || !CHARACTER_LIVE2D[robot.name]) return;
    const next: DisplayMode = displayMode === "2d" ? "live2d" : "2d";
    setDisplayMode(next);
    storeMode(robot.name, next);
  }, [robot, displayMode]);

  const switchRobot = useCallback((r: Robot) => {
    setRobot(r);
    setShowSettings(false);
    setCharacterState("idle");
    setSubtitle("");
    setMsgVersion((v) => v + 1);
  }, []);

  const handleClear = useCallback(() => {
    if (!robot) return;
    chatMap.current.set(robot.id, { conversationId: null, messages: [] });
    setMsgVersion((v) => v + 1);
  }, [robot]);

  const handleSend = useCallback(
    async (text: string) => {
      console.log("[handleSend] called with:", text, "robot:", robot?.name);
      if (!robot || !text.trim()) {
        console.log("[handleSend] early return: robot=", !!robot, "text=", text);
        return;
      }

      setIsWaiting(true);
      setCharacterState("thinking");
      showSubtitle("");

      try {
        let convId = getChatState().conversationId;
        if (!convId) {
          const conv = await api.createConversation();
          convId = conv.id;
          updateChatState({ conversationId: convId });
        }

        // Add user message
        const userMsg: ChatMessage = {
          id: `user-${Date.now()}`,
          sender_type: "user",
          sender_id: null,
          sender_name: "主人",
          content: text,
          emotion: null,
          created_at: new Date().toISOString(),
        };
        const currentMessages = getChatState().messages;
        updateChatState({ messages: [...currentMessages, userMsg] });
        setMsgVersion((v) => v + 1);

        // Use agent chat (no screen capture for regular chat)
        const result = await api.agentChat(text, robot.id, convId);

        // Add bot reply
        const botMsg: ChatMessage = {
          id: `bot-${Date.now()}`,
          sender_type: "robot",
          sender_id: robot.id,
          sender_name: robot.name,
          content: result.reply,
          emotion: null,
          created_at: new Date().toISOString(),
          _japanese: result.reply_ja,
          _emotion: result.emotion,
        };
        const updatedMessages = getChatState().messages;
        updateChatState({ messages: [...updatedMessages, botMsg] });
        setMsgVersion((v) => v + 1);

        // Show floating subtitle
        showSubtitle(result.reply);

        // Execute desktop actions
        if (result.desktop_actions.length > 0 && window.nomi?.agent?.executeAction) {
          for (const action of result.desktop_actions) {
            window.nomi.agent.executeAction(action).catch(console.error);
          }
        }

        // Set emotion for speaking
        const emotionState = result.emotion === "Sad" ? "sad"
          : result.emotion === "Surprised" ? "surprised"
          : result.emotion === "Happy" ? "happy"
          : "speaking";

        if (voiceEnabled) {
          const ttsLang = ROBOT_TTS_LANG[robot.name] || "japanese";
          const ttsText = ttsLang === "japanese" ? result.reply_ja : result.reply;

          if (ttsText) {
            // Text arrived → listening (preparing voice)
            setCharacterState("listening");
            try {
              // playTts fetches audio then plays — switch to emotion when playing starts
              const blob = await api.fetchTtsBlob(ttsText, robot.name, result.emotion || "Normal");
              if (blob) {
                setCharacterState(emotionState as CharacterState);
                await playTtsBlob(blob);
              }
            } catch (e) {
              console.error("TTS failed:", e);
            }
          } else {
            setCharacterState(emotionState as CharacterState);
            await new Promise(r => setTimeout(r, 2000));
          }
        } else {
          setCharacterState(emotionState as CharacterState);
          await new Promise(r => setTimeout(r, 2000));
        }

        setCharacterState("idle");
      } catch (err: any) {
        console.error("Send failed:", err?.message, err);
        showSubtitle("发送失败: " + String(err?.message || err));
        setCharacterState("idle");
      } finally {
        setIsWaiting(false);
      }
    },
    [robot, msgVersion]
  );

  if (!backendReady) {
    return <LoadingScreen />;
  }

  const characterDir = robot
    ? (CHARACTER_DIRS[robot.name] || `http://127.0.0.1:8100/api/admin/characters/${robot.id}/image`)
    : "./characters/frieren";
  const currentMessages = getChatState().messages;

  return (
    <div className="flex flex-row h-screen bg-transparent">
      {/* Left: Avatar + controls */}
      <div className="relative flex flex-col items-center flex-shrink-0 pt-2" style={{ width: showChat ? "340px" : "100%" }}>
        {/* Top bar: character name + controls */}
        <div className="flex items-center gap-2 z-10">
          {robot && (
            <button
              onClick={() => setShowSettings(!showSettings)}
              className="text-xs text-gray-500 hover:text-gray-700 transition-colors"
            >
              {robot.name}
              <span className="ml-1 text-[10px] text-gray-300">▼</span>
            </button>
          )}
          <button
            onClick={() => setShowAgentSettings(true)}
            className="w-5 h-5 flex items-center justify-center rounded text-gray-300 hover:text-gray-500 transition-colors"
            title="Agent 设置"
          >
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
            </svg>
          </button>
          <button
            onClick={async () => {
              if (!robot || isWaiting) return;
              try {
                setSubtitle("观察中...");
                setCharacterState("thinking");
                const ctx = await window.nomi.agent.getDesktopContext();
                if (!ctx.screenDescription) {
                  setSubtitle("截屏失败");
                  setCharacterState("idle");
                  return;
                }

                // Call react API to let character comment on what it sees
                const result = await api.agentReact(
                  ctx.screenDescription,
                  "用户点击了观察按钮，请根据屏幕内容分享你的想法",
                  robot.id,
                  { active_app: ctx.activeApp, window_title: ctx.windowTitle }
                );

                if (result.reaction) {
                  // Show reaction in chat
                  const reactMsg: ChatMessage = {
                    id: `react-${Date.now()}`,
                    sender_type: "robot",
                    sender_id: robot.id,
                    sender_name: robot.name,
                    content: result.reaction,
                    emotion: null,
                    created_at: new Date().toISOString(),
                    _japanese: result.reaction_ja,
                    _emotion: result.emotion,
                    _isReaction: true,
                  };
                  const current = getChatState().messages;
                  updateChatState({ messages: [...current, reactMsg] });
                  setMsgVersion((v) => v + 1);
                  showSubtitle(result.reaction);

                  // Set emotion
                  const emotionState = result.emotion === "Sad" ? "sad"
                    : result.emotion === "Surprised" ? "surprised"
                    : result.emotion === "Happy" ? "happy"
                    : "speaking";
                  setCharacterState(emotionState as CharacterState);

                  // Play TTS if enabled
                  if (voiceEnabled && result.reaction_ja) {
                    try {
                      await playTts(result.reaction_ja, robot.name, result.emotion || "Normal");
                    } catch (e) {
                      console.error("TTS failed:", e);
                    }
                  }
                }
                setCharacterState("idle");
              } catch (e) {
                setSubtitle("观察失败: " + String(e));
                setCharacterState("idle");
                console.error("[observe]", e);
              }
            }}
            className="w-5 h-5 flex items-center justify-center rounded text-gray-300 hover:text-gray-500 transition-colors"
            title="观察屏幕"
          >
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="12" cy="12" r="3" />
            </svg>
          </button>
          {robot && CHARACTER_LIVE2D[robot.name] && (
            <button
              onClick={toggleDisplayMode}
              className="px-1.5 py-0.5 rounded text-[9px] font-medium text-gray-400 hover:text-gray-600 bg-white/40 hover:bg-white/60 transition-all"
              title={displayMode === "2d" ? "切换到 Live2D" : "切换到 2D"}
            >
              {displayMode === "2d" ? "3D" : "2D"}
            </button>
          )}
          <button
            onClick={toggleHeartbeat}
            className={`px-1.5 py-0.5 rounded text-[9px] font-medium transition-all ${
              heartbeatOn
                ? "bg-red-100 text-red-500"
                : "text-gray-400 hover:text-gray-600 bg-white/40 hover:bg-white/60"
            }`}
            title={heartbeatOn ? "关闭心跳" : "开启心跳"}
          >
            {heartbeatOn ? "❤️" : "🤍"}
          </button>
          {agentStatus !== "idle" && (
            <span className="text-[10px] text-gray-400">
              {agentStatus === "sensing" ? "👁" : agentStatus === "analyzing" ? "🔍" : agentStatus === "reacting" ? "⚡" : ""}
            </span>
          )}
        </div>

        {/* Avatar */}
        <div className="flex-1 flex items-end justify-center pb-2">
          <AvatarSwitch
            characterDir={characterDir}
            live2dModelPath={robot ? CHARACTER_LIVE2D[robot.name] : undefined}
            live2dScale={(robot?.voice_profile as any)?.live2d_scale}
            state={characterState}
            onClick={() => setShowChat(!showChat)}
            mode={displayMode}
          />
        </div>

        {/* Floating subtitle */}
        {subtitle && (
          <div className="absolute bottom-24 left-2 right-2 flex justify-center z-10 pointer-events-none">
            <div className="bg-black/50 backdrop-blur-md text-white text-[12px] leading-relaxed px-4 py-2 rounded-2xl max-w-[95%] text-center shadow-lg max-h-[120px] overflow-y-auto pointer-events-auto">
              {subtitle}
            </div>
          </div>
        )}

        {/* Bottom: voice button + chat toggle */}
        <div className="flex items-center gap-4 pb-4 z-10">
          <VoiceButton
            onTranscribed={handleSend}
            disabled={isWaiting}
          />
          <button
            onClick={() => setShowChat(!showChat)}
            className={`w-10 h-10 rounded-full flex items-center justify-center transition-all ${
              showChat ? "bg-purple-400 text-white shadow-md" : "bg-white/60 text-gray-400 hover:bg-white/80 hover:text-gray-600"
            }`}
            title="聊天记录"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
            </svg>
          </button>
        </div>
      </div>

      {/* Right: Chat panel (does not overlap avatar) */}
      {showChat && (
        <div className="flex-1 my-4 mr-4 ml-1 bg-white/80 backdrop-blur-lg rounded-2xl overflow-hidden shadow-xl border border-white/30">
          <ChatPanel
            messages={currentMessages}
            onSend={handleSend}
            onClear={handleClear}
            isWaiting={isWaiting}
          />
        </div>
      )}

      {showAgentSettings && (
        <AgentSettings
          onClose={() => setShowAgentSettings(false)}
          robot={robot}
          heartbeatInterval={heartbeatInterval}
          onHeartbeatIntervalChange={(v) => setHeartbeatIntervalState(v)}
        />
      )}

      {/* Character switcher — top-level overlay so nothing blocks it */}
      {showSettings && (
        <div className="fixed inset-0 z-50" onClick={() => setShowSettings(false)}>
          <div className="absolute top-10 left-1/2 -translate-x-1/2 w-[240px]" onClick={(e) => e.stopPropagation()}>
            <div className="bg-white/95 backdrop-blur-lg rounded-xl shadow-2xl border border-white/30 overflow-hidden">
              <div className="px-3 py-2 space-y-1.5 max-h-[250px] overflow-y-auto">
                {robots.map((r) => {
                  const isActive = robot?.id === r.id;
                  const avatarSrc = CHARACTER_DIRS[r.name]
                    ? `${CHARACTER_DIRS[r.name]}/idle.png`
                    : `http://127.0.0.1:8100/api/admin/characters/${r.id}/image/idle`;
                  return (
                    <button
                      key={r.id}
                      onClick={() => switchRobot(r)}
                      className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg transition-all ${
                        isActive ? "bg-purple-50 border border-purple-200" : "hover:bg-gray-50 border border-transparent"
                      }`}
                    >
                      <img src={avatarSrc} alt={r.name} className="w-8 h-8 rounded-full object-cover object-top bg-gray-100" />
                      <p className={`text-xs font-medium ${isActive ? "text-purple-600" : "text-gray-700"}`}>{r.name}</p>
                      {isActive && <div className="ml-auto w-1.5 h-1.5 rounded-full bg-purple-400" />}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
