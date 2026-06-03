import Link from "next/link";
import type { Robot } from "@/lib/types";

const ORB_GRADIENTS = [
  "from-nomi-rose to-nomi-apricot",
  "from-nomi-lavender to-nomi-rose-light",
  "from-nomi-apricot to-nomi-sage-light",
  "from-nomi-sage to-nomi-lavender",
];

export default function RobotCard({
  robot,
  index,
  onDelete,
}: {
  robot: Robot;
  index: number;
  onDelete?: (id: string) => void;
}) {
  const gradient = ORB_GRADIENTS[index % ORB_GRADIENTS.length];
  const initial = robot.name.charAt(0);
  const emotion = robot.current_emotion?.emotion || "平静";
  const avatar = (robot.voice_profile as Record<string, string> | null)?.avatar;

  return (
    <div className="relative">
      <Link href={`/robots/${robot.id}`}>
        <div className="glass shadow-nomi group flex items-center gap-4 rounded-[20px] p-4 transition-all duration-300 hover:shadow-lg hover:scale-[1.01]">
          {avatar ? (
            <img src={avatar} alt={robot.name} className="h-12 w-12 shrink-0 rounded-full object-cover shadow-sm" />
          ) : (
            <div className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-gradient-to-br ${gradient} text-lg font-semibold text-white shadow-sm`}>
              {initial}
            </div>
          )}
          <div className="min-w-0 flex-1">
            <h3 className="text-[15px] font-semibold tracking-wide">{robot.name}</h3>
            <p className="mt-0.5 text-xs text-nomi-charcoal-soft">
              {robot.age}岁 · {emotion} · {robot.personality?.slice(0, 2).join(" / ") || ""}
            </p>
          </div>
          {!onDelete && (
            <svg className="h-4 w-4 text-nomi-warm-gray opacity-0 transition-opacity group-hover:opacity-100" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
            </svg>
          )}
          {onDelete && <div className="w-7 shrink-0" />}
        </div>
      </Link>
      {onDelete && (
        <button
          onClick={(e) => { e.preventDefault(); onDelete(robot.id); }}
          className="absolute right-3 top-1/2 -translate-y-1/2 flex h-7 w-7 items-center justify-center rounded-full text-nomi-charcoal-muted opacity-40 transition-opacity hover:bg-red-50 hover:text-red-400 hover:opacity-100"
          aria-label="删除"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
          </svg>
        </button>
      )}
    </div>
  );
}
