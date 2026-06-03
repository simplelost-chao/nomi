import type { ChatMessage } from "@/lib/types";

const SENDER_COLORS: Record<string, string> = {
  robot: "bg-white/70",
  user: "bg-nomi-apricot-light",
  system: "bg-nomi-gray-light",
};

const AVATAR_COLORS = [
  "bg-nomi-rose-light",
  "bg-nomi-lavender-light",
  "bg-nomi-apricot-light",
  "bg-nomi-sage-light",
];

export default function ChatBubble({
  message,
  avatarIndex = 0,
}: {
  message: ChatMessage;
  avatarIndex?: number;
}) {
  const isUser = message.sender_type === "user";
  const bgColor = SENDER_COLORS[message.sender_type || "robot"] || "bg-white/70";
  const avatarColor = isUser
    ? "bg-nomi-apricot"
    : AVATAR_COLORS[avatarIndex % AVATAR_COLORS.length];
  const initial = (message.sender_name || "?").charAt(0);

  return (
    <div className={`flex gap-3 ${isUser ? "flex-row-reverse" : ""}`}>
      <div
        className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${avatarColor} text-sm font-semibold text-nomi-charcoal`}
      >
        {initial}
      </div>
      <div className={`max-w-[75%] rounded-2xl px-4 py-2.5 ${bgColor} nomi-glow`}>
        {!isUser && (
          <p className="mb-1 text-xs font-medium text-nomi-gray">
            {message.sender_name}
          </p>
        )}
        <p className="text-sm leading-relaxed">{message.content}</p>
      </div>
    </div>
  );
}
