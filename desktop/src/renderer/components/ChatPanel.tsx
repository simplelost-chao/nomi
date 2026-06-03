import { useEffect, useRef, useState } from "react";
import { ChatBubble } from "./ChatBubble";
import type { ChatMessage } from "../types";

interface ChatPanelProps {
  messages: ChatMessage[];
  onSend: (text: string) => void;
  onClear?: () => void;
  isWaiting: boolean;
}

export function ChatPanel({ messages, onSend, onClear, isWaiting }: ChatPanelProps) {
  const [input, setInput] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isWaiting]);

  function handleSend() {
    const text = input.trim();
    if (!text || isWaiting) return;
    setInput("");
    onSend(text);
    if (inputRef.current) inputRef.current.style.height = "auto";
    setTimeout(() => inputRef.current?.focus(), 0);
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      handleSend();
    }
  }

  function handleInput(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setInput(e.target.value);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 96) + "px";
  }

  return (
    <div className="flex flex-col h-full" style={{ padding: "24px" }}>
      {/* Header */}
      <div className="flex-shrink-0 pb-4">
        <div className="flex items-center justify-between">
          <div className="flex items-baseline gap-3">
            <span className="text-[18px] font-bold text-gray-800">对话</span>
            {messages.length > 0 && (
              <span className="text-[13px] text-gray-400">{messages.length} 条消息</span>
            )}
          </div>
          {messages.length > 0 && onClear && (
            <button
              onClick={onClear}
              className="flex items-center gap-2 px-4 py-2 text-[13px] text-gray-500 hover:text-red-400 hover:bg-red-50 rounded-xl transition-colors border border-gray-200/80 hover:border-red-200"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
              </svg>
              清空对话
            </button>
          )}
        </div>
        <div className="w-8 h-[3px] bg-purple-500 rounded-full mt-3" />
      </div>

      {/* Messages */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto py-4 space-y-8 -mx-1 px-1"
      >
        {messages.length === 0 && !isWaiting && (
          <div className="flex items-center justify-center h-full">
            <p className="text-[14px] text-gray-300">说点什么开始聊天吧</p>
          </div>
        )}
        {messages.map((msg, i) => (
          <ChatBubble
            key={msg.id}
            text={msg.content || ""}
            isUser={msg.sender_type === "user"}
            senderName={msg.sender_name || undefined}
            japaneseText={msg._japanese}
            emotion={msg._emotion}
            timestamp={msg.created_at}
            typewriter={msg.sender_type !== "user" && i === messages.length - 1}
            isReaction={msg._isReaction}
          />
        ))}
        {isWaiting && (
          <div className="flex items-start gap-3">
            <div className="flex-shrink-0 w-12 h-12 rounded-full bg-gradient-to-br from-purple-300 to-purple-400 flex items-center justify-center shadow-sm">
              <span className="text-[12px] text-white font-medium">AI</span>
            </div>
            <div className="px-5 py-4 bg-white/80 rounded-2xl rounded-tl-md shadow-sm border border-gray-100/80 mt-6">
              <span className="inline-flex gap-1.5 items-center">
                <span className="w-2 h-2 bg-purple-300 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                <span className="w-2 h-2 bg-purple-300 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                <span className="w-2 h-2 bg-purple-300 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Input area */}
      <div className="flex-shrink-0 pt-4">
        <div className="bg-white/60 backdrop-blur-sm rounded-2xl border border-gray-200/50 shadow-sm p-3">
          <textarea
            ref={inputRef}
            value={input}
            onChange={handleInput}
            onKeyDown={handleKeyDown}
            placeholder="输入消息，回车发送..."
            disabled={isWaiting}
            autoFocus
            rows={1}
            className="w-full px-3 pt-2 pb-1 text-[15px] bg-transparent outline-none resize-none leading-relaxed text-gray-700 placeholder-gray-400 disabled:opacity-50"
            style={{ minHeight: "36px", maxHeight: "80px" }}
          />
          <div className="flex items-center justify-between px-2 pt-2">
            <div className="flex items-center gap-2">
              <button className="w-8 h-8 flex items-center justify-center rounded-lg text-gray-400 hover:text-purple-500 hover:bg-purple-50 transition-all">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="10" /><path d="M8 14s1.5 2 4 2 4-2 4-2" /><line x1="9" y1="9" x2="9.01" y2="9" /><line x1="15" y1="9" x2="15.01" y2="9" />
                </svg>
              </button>
              <button className="w-8 h-8 flex items-center justify-center rounded-lg text-gray-400 hover:text-purple-500 hover:bg-purple-50 transition-all">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
                </svg>
              </button>
              <button className="w-8 h-8 flex items-center justify-center rounded-lg text-gray-400 hover:text-purple-500 hover:bg-purple-50 transition-all">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 2L9 9H2l6 5-2 7 6-4 6 4-2-7 6-5h-7z" />
                </svg>
              </button>
            </div>
            <button
              onClick={handleSend}
              disabled={isWaiting || !input.trim()}
              className="w-11 h-11 flex items-center justify-center rounded-xl bg-gradient-to-br from-purple-500 to-purple-600 text-white disabled:opacity-30 hover:from-purple-600 hover:to-purple-700 active:scale-95 transition-all shadow-lg"
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
              </svg>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
