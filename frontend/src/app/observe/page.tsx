"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { ObjectObservation } from "@/lib/types";
import ReactionCard from "@/app/components/ReactionCard";

export default function ObservePage() {
  const router = useRouter();
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ObjectObservation | null>(null);

  const handleSubmit = async () => {
    if (!text.trim()) return;
    setLoading(true);
    try {
      const observation = await api.observeObject(text.trim());
      setResult(observation);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <button
        onClick={() => router.push("/")}
        className="mb-4 text-sm text-stone-400 hover:text-stone-600"
      >
        ← 回到房间
      </button>

      <h1 className="mb-6 text-xl font-bold">给小生命们看一个东西</h1>

      {/* Input */}
      {!result && (
        <div className="mb-6">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="描述一个物品，比如：一个旧旧的布娃娃，耳朵上有缝补的痕迹..."
            rows={4}
            className="w-full rounded-2xl border border-stone-200 bg-white p-4 text-sm focus:border-amber-300 focus:outline-none focus:ring-1 focus:ring-amber-300"
          />
          <button
            onClick={handleSubmit}
            disabled={loading || !text.trim()}
            className="mt-3 w-full rounded-full bg-amber-400 py-3 font-medium text-white shadow-sm transition-all hover:bg-amber-500 disabled:opacity-50"
          >
            {loading ? "小生命们正在观察..." : "让它们看看"}
          </button>
        </div>
      )}

      {/* Results */}
      {result && (
        <div>
          {/* Object description */}
          <div className="mb-4 rounded-2xl bg-white p-4 shadow-sm">
            <h2 className="mb-1 font-semibold">
              {result.object_name}
            </h2>
            <p className="mb-2 text-sm text-stone-500">
              {result.object_description}
            </p>
            {result.symbolic_tags && (
              <div className="flex flex-wrap gap-1">
                {result.symbolic_tags.map((tag) => (
                  <span
                    key={tag}
                    className="rounded-full bg-stone-100 px-2 py-0.5 text-xs text-stone-500"
                  >
                    #{tag}
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* Reactions */}
          <h2 className="mb-3 font-semibold">它们的反应</h2>
          <div className="mb-6 space-y-3">
            {result.reactions.map((reaction, i) => (
              <ReactionCard key={reaction.robot_id} reaction={reaction} index={i} />
            ))}
          </div>

          {/* Actions */}
          <div className="flex gap-3">
            <button
              onClick={() => {
                setResult(null);
                setText("");
              }}
              className="flex-1 rounded-full bg-white py-3 text-center font-medium shadow-sm"
            >
              再看一个
            </button>
            <button
              onClick={() => {
                const topic = `讨论${result.object_name || "这个物品"}`;
                router.push(`/chat?topic=${encodeURIComponent(topic)}`);
              }}
              className="flex-1 rounded-full bg-amber-400 py-3 text-center font-medium text-white shadow-sm"
            >
              让它们聊聊这个
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
