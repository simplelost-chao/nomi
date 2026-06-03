import { useEffect, useState } from "react";
import { api } from "../api";
import { ROBOT_TTS_LANG, CHARACTER_DIRS } from "../types";

interface ChatBubbleProps {
  text: string;
  isUser: boolean;
  senderName?: string;
  japaneseText?: string;
  emotion?: string;
  timestamp?: string;
  typewriter?: boolean;
  onTypingDone?: () => void;
  isReaction?: boolean;
}

function formatTime(ts?: string): string {
  if (!ts) return "";
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  } catch { return ""; }
}

export function ChatBubble({ text, isUser, senderName, japaneseText, emotion, timestamp, typewriter = false, onTypingDone, isReaction }: ChatBubbleProps) {
  const [displayText, setDisplayText] = useState(typewriter ? "" : text);
  const [isSpeaking, setIsSpeaking] = useState(false);

  useEffect(() => {
    if (!typewriter) {
      setDisplayText(text);
      return;
    }
    let index = 0;
    const timer = setInterval(() => {
      index++;
      setDisplayText(text.slice(0, index));
      if (index >= text.length) {
        clearInterval(timer);
        onTypingDone?.();
      }
    }, 33);
    return () => clearInterval(timer);
  }, [text, typewriter, onTypingDone]);

  async function handleSpeak() {
    if (isSpeaking || !senderName) return;
    setIsSpeaking(true);
    try {
      const ttsLang = ROBOT_TTS_LANG[senderName] || "japanese";
      const ttsText = ttsLang === "japanese" && japaneseText ? japaneseText : text;
      await api.speak(ttsText, senderName, emotion || "Normal");
    } catch (e) {
      console.warn("TTS failed:", e);
    } finally {
      setIsSpeaking(false);
    }
  }

  const time = formatTime(timestamp);

  // User message
  if (isUser) {
    return (
      <div className="flex flex-col items-end gap-2">
        {time && <span className="text-[11px] text-gray-400 mr-14">{time}</span>}
        <div className="flex flex-row-reverse items-end gap-3">
          <div className="flex-shrink-0 w-10 h-10 rounded-full bg-gradient-to-br from-purple-400 to-purple-500 flex items-center justify-center shadow-sm">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="white">
              <path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z" />
            </svg>
          </div>
          <div className="max-w-[75%] px-5 py-3 text-[15px] leading-relaxed break-words bg-gradient-to-br from-purple-400 to-purple-500 text-white rounded-2xl rounded-br-md shadow-sm">
            {displayText}
          </div>
        </div>
      </div>
    );
  }

  // Bot message - card style matching screenshot
  const characterDir = senderName ? (CHARACTER_DIRS[senderName] || "./characters/frieren") : "./characters/frieren";

  return (
    <div className="flex items-start gap-3">
      {/* Avatar - outside the card */}
      <div className="flex-shrink-0 w-12 h-12 rounded-full overflow-hidden bg-gray-100 shadow-sm mt-1">
        <img
          src={`${characterDir}/idle.png`}
          alt={senderName || "AI"}
          className="w-full h-full object-cover"
        />
      </div>

      {/* Message card */}
      <div className="flex-1 min-w-0 max-w-[85%]">
        {/* Name + time */}
        <div className="flex items-center gap-3 mb-2">
          {isReaction && <span className="text-[11px]">👁</span>}
          {senderName && <span className="text-[13px] text-gray-600 font-medium">{senderName}</span>}
          {time && <span className="text-[12px] text-gray-400">{time}</span>}
        </div>

        {/* Text bubble with actions inside one card */}
        <div className={`relative ${isReaction ? "bg-purple-50/80" : "bg-white/80"} rounded-2xl rounded-tl-md shadow-sm border border-gray-100/80 px-5 pt-4 pb-3`}>
          <p className="text-[15px] leading-relaxed text-gray-800 break-words">
            {displayText}
            {typewriter && displayText.length < text.length && (
              <span className="animate-pulse ml-0.5 text-purple-300">|</span>
            )}
          </p>

          {/* Decorative sparkle */}
          <span className="absolute bottom-2 right-3 text-purple-300/60 text-[14px]">✦</span>

          {/* Action buttons - inside the card */}
          {text && (
            <div className="flex items-center gap-4 mt-3 pt-2 border-t border-gray-100/60">
              <button
                onClick={handleSpeak}
                disabled={isSpeaking}
                className="w-8 h-8 flex items-center justify-center rounded-lg text-gray-400 hover:text-purple-500 hover:bg-purple-50 disabled:opacity-30 transition-all"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" /><path d="M15.54 8.46a5 5 0 0 1 0 7.07" />
                </svg>
              </button>
              <button className="w-8 h-8 flex items-center justify-center rounded-lg text-gray-400 hover:text-purple-500 hover:bg-purple-50 transition-all">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" />
                </svg>
              </button>
              <button className="w-8 h-8 flex items-center justify-center rounded-lg text-gray-400 hover:text-purple-500 hover:bg-purple-50 transition-all">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="9" y="9" width="13" height="13" rx="2" ry="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                </svg>
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
