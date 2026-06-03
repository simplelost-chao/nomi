import type { RobotReaction } from "@/lib/types";

const COLORS = [
  "border-nomi-rose",
  "border-nomi-lavender",
  "border-nomi-apricot",
  "border-nomi-sage",
];

export default function ReactionCard({
  reaction,
  index,
}: {
  reaction: RobotReaction;
  index: number;
}) {
  const borderColor = COLORS[index % COLORS.length];

  return (
    <div className={`rounded-2xl border-2 ${borderColor} bg-white/70 p-4`}>
      <div className="mb-2 flex items-center gap-2">
        <span className="font-semibold">{reaction.robot_name}</span>
        {reaction.emotion_change && (
          <span className="text-xs text-nomi-gray">
            {reaction.emotion_change.emotion}
          </span>
        )}
      </div>
      <p className="mb-2 text-xs italic text-nomi-charcoal-light">
        {reaction.inner_thought}
      </p>
      <p className="text-sm">{reaction.user_expression}</p>
    </div>
  );
}
