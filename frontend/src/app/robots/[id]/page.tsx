"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { RobotDetail } from "@/lib/types";

const TAG_COLORS = [
  "bg-nomi-rose-light text-nomi-charcoal",
  "bg-nomi-lavender-light text-nomi-charcoal",
  "bg-nomi-apricot-light text-nomi-charcoal",
  "bg-nomi-sage-light text-nomi-charcoal",
];

const MODELS = [
  { id: "deepseek-v4-flash", label: "DeepSeek Flash" },
  { id: "deepseek-v4-pro", label: "DeepSeek Pro" },
  { id: "claude", label: "Claude" },
];

function RegenButton({ label, robotId, module, onDone }: {
  label: string; robotId: string; module: string; onDone: () => void;
}) {
  const [loading, setLoading] = useState(false);
  const [model, setModel] = useState("deepseek-v4-flash");

  return (
    <div className="flex items-center gap-1.5">
      <select value={model} onChange={(e) => setModel(e.target.value)}
        className="rounded bg-nomi-cream px-1.5 py-0.5 text-[10px] text-nomi-charcoal-muted focus:outline-none">
        {MODELS.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
      </select>
      <button
        onClick={async () => {
          setLoading(true);
          try {
            await fetch(`/api/robots/${robotId}/regenerate/${module}?model=${model}`, { method: "POST" });
            onDone();
          } catch (e) { console.error(e); }
          finally { setLoading(false); }
        }}
        disabled={loading}
        className="rounded-full bg-nomi-warm-gray/20 px-2 py-0.5 text-[10px] text-nomi-charcoal-muted active:bg-nomi-rose-light disabled:opacity-50"
      >
        {loading ? "..." : `🔄 ${label}`}
      </button>
    </div>
  );
}

export default function RobotDetailPage() {
  const params = useParams();
  const router = useRouter();
  const [robot, setRobot] = useState<RobotDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"profile" | "memories" | "relationships" | "activity" | "skills">("profile");
  type Activity = { id: string; event_type: string; content: string; detail: Record<string, unknown> | null; created_at: string };
  const [activities, setActivities] = useState<Activity[]>([]);
  const [activityTotal, setActivityTotal] = useState(0);
  const [activityPage, setActivityPage] = useState(0);
  const ACTIVITY_PAGE_SIZE = 20;
  const [skills, setSkills] = useState<{ id: string; name: string; description: string | null; trigger_keywords: string[]; skill_type: string | null; usage_count: number; acquired_at: string | null }[]>([]);
  const [voiceRegenState, setVoiceRegenState] = useState<"idle" | "confirm" | "loading" | "done">("idle");
  const [voiceRegenFeel, setVoiceRegenFeel] = useState<string>("");
  const [triggerState, setTriggerState] = useState<Record<string, "idle" | "loading" | "done" | "error">>({});

  const triggerAction = async (action: string) => {
    if (!robot) return;
    setTriggerState(s => ({ ...s, [action]: "loading" }));
    try {
      const res = await fetch(`/api/heartbeat/trigger/${robot.id}/${action}`, {
        method: "POST",
        signal: AbortSignal.timeout(120_000),
      });
      if (!res.ok) throw new Error(`${res.status}`);
      setTriggerState(s => ({ ...s, [action]: "done" }));
      setActivityPage(0);
      setTimeout(() => {
        setTriggerState(s => ({ ...s, [action]: "idle" }));
        loadActivities(0);
      }, 1500);
    } catch {
      setTriggerState(s => ({ ...s, [action]: "error" }));
      setTimeout(() => setTriggerState(s => ({ ...s, [action]: "idle" })), 2000);
    }
  };

  const reload = () => {
    api.getRobot(params.id as string).then(setRobot).catch(console.error);
  };

  const loadSkills = () => {
    fetch(`/api/robots/${params.id}/skills`)
      .then((r) => r.json())
      .then(setSkills)
      .catch(console.error);
  };

  const loadActivities = (page = activityPage) => {
    const offset = page * ACTIVITY_PAGE_SIZE;
    fetch(`/api/robots/${params.id}/activity?limit=${ACTIVITY_PAGE_SIZE}&offset=${offset}`)
      .then(r => r.json())
      .then(data => {
        setActivities(data.items ?? []);
        setActivityTotal(data.total ?? 0);
      })
      .catch(console.error);
  };

  // Load robot data
  useEffect(() => {
    if (params.id) {
      api.getRobot(params.id as string).then(setRobot).catch(console.error).finally(() => setLoading(false));
    }
  }, [params.id]);

  // Auto-refresh if creating — but treat as done if all steps finished
  const steps = (robot?.generation_stats?.steps as { status: string }[]) || [];
  const allStepsDone = steps.length > 0 && steps.every(s => s.status === "done");
  const isCreating = robot?.generation_stats?.status === "creating" && !allStepsDone;
  useEffect(() => {
    if (!isCreating) return;
    const interval = setInterval(() => reload(), 3000);
    return () => clearInterval(interval);
  }, [isCreating]);

  // --- Loading ---
  if (loading) {
    return <div className="flex min-h-[60vh] items-center justify-center"><div className="nomi-orb h-12 w-12" /></div>;
  }

  if (!robot) {
    return (
      <div className="text-center">
        <p className="text-nomi-charcoal-light">找不到这个小生命</p>
        <button onClick={() => router.push("/")} className="mt-4 text-nomi-rose underline">回到房间</button>
      </div>
    );
  }

  // --- Creating ---
  if (isCreating) {
    const steps = (robot.generation_stats?.steps as { id: string; label: string; status: string; detail?: string; time_ms?: number }[]) || [];
    return (
      <div>
        <button onClick={() => router.push("/")} className="mb-4 text-sm text-nomi-gray hover:text-nomi-charcoal">← 回到房间</button>
        <div className="mb-6 text-center">
          <div className="nomi-orb mx-auto mb-4 h-16 w-16" />
          <h1 className="text-xl font-semibold">{robot.name} 正在诞生...</h1>
        </div>
        <div className="glass-strong shadow-nomi rounded-[20px] p-5 space-y-3">
          {steps.map((step) => (
            <div key={step.id} className="flex items-start gap-3">
              <div className="mt-0.5 shrink-0">
                {step.status === "done" && <span className="text-base">✅</span>}
                {step.status === "running" && <div className="nomi-orb h-5 w-5" />}
                {step.status === "pending" && <span className="inline-block h-5 w-5 rounded-full border-2 border-nomi-warm-gray/30" />}
              </div>
              <div>
                <p className={`text-[13px] ${step.status === "running" ? "font-semibold" : step.status === "done" ? "text-nomi-charcoal-soft" : "text-nomi-charcoal-muted"}`}>
                  {step.label}
                </p>
                {step.detail && <p className="mt-0.5 text-xs text-nomi-charcoal-muted">{step.detail}</p>}
              </div>
            </div>
          ))}
        </div>
        <button onClick={() => {
          // Force status to non-creating so detail view shows
          if (robot) setRobot({ ...robot, generation_stats: { ...robot.generation_stats, status: "done" } });
        }} className="mt-4 w-full rounded-full border border-nomi-warm-gray/30 py-2.5 text-sm text-nomi-charcoal-muted hover:text-nomi-charcoal transition-colors">
          跳过，直接查看
        </button>
      </div>
    );
  }

  // --- Detail View ---
  const GENDER_LABEL: Record<string, string> = {
    "male": "♂ 男性",
    "female": "♀ 女性",
    "neutral": "◇ 中性",
    "neutral-male": "◈ 偏男性",
    "neutral-female": "◈ 偏女性",
  };
  const sortedMemories = [...(robot.yearly_memories || [])].sort((a, b) => a.age - b.age);
  const memsByAge = new Map<number, typeof sortedMemories>();
  for (const mem of sortedMemories) {
    const list = memsByAge.get(mem.age) || [];
    list.push(mem);
    memsByAge.set(mem.age, list);
  }
  const ages = [...memsByAge.keys()].sort((a, b) => a - b);

  return (
    <div className="space-y-4">
      <button onClick={() => router.push("/")} className="text-sm text-nomi-gray hover:text-nomi-charcoal">← 回到房间</button>

      {/* Header + Voice */}
      <div className="glass shadow-nomi rounded-[20px] p-5">
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            {(() => {
              const avatarUrl = (robot.voice_profile as Record<string, string> | null)?.avatar;
              return avatarUrl
                ? <img src={avatarUrl} alt={robot.name} className="h-14 w-14 shrink-0 rounded-full object-cover shadow-sm" />
                : <div className="nomi-orb h-14 w-14 shrink-0" />;
            })()}
            <div>
              <h1 className="text-xl font-semibold">{robot.name}</h1>
              <div className="mt-0.5 flex items-center gap-1.5 flex-wrap">
                <p className="text-xs text-nomi-charcoal-muted">{robot.age}岁 · {robot.birth_place}</p>
                {(() => {
                  // Portrait gender_feel (new portraits) or voice_profile fallback
                  const raw = (robot.portrait as Record<string, unknown> | null)?.gender_feel as string | undefined
                    || robot.voice_profile?.gender_feeling;
                  const label = raw ? (GENDER_LABEL[raw] ?? raw) : null;
                  return label ? (
                    <span className="rounded-full bg-nomi-lavender-light px-2 py-0.5 text-[10px] font-medium text-nomi-charcoal-soft">
                      {label}
                    </span>
                  ) : null;
                })()}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {/* Voice regen button — idle → confirm → loading → done */}
            {voiceRegenState === "idle" && (
              <button
                onClick={() => setVoiceRegenState("confirm")}
                className="rounded-full bg-nomi-warm-gray/20 px-2.5 py-1 text-[10px] text-nomi-charcoal-muted hover:bg-nomi-warm-gray/40 transition-colors"
                title="换一个声音"
              >🔄 换声音</button>
            )}
            {voiceRegenState === "confirm" && (
              <div className="flex items-center gap-1.5 rounded-full bg-nomi-apricot-light/80 px-2.5 py-1">
                <span className="text-[10px] text-nomi-charcoal-soft">确定换声音？</span>
                <button
                  onClick={async () => {
                    setVoiceRegenState("loading");
                    try {
                      const res = await fetch(`/api/tts/regenerate/${robot.id}`, { method: "POST" });
                      const data = await res.json();
                      setVoiceRegenFeel(data?.voice?.feel || "新声音");
                      setVoiceRegenState("done");
                      // Auto-play new voice
                      const el = document.getElementById("voice-sample") as HTMLAudioElement;
                      if (el) {
                        el.src = `/api/tts/speak?text=${encodeURIComponent(`你好，我是${robot.name}。${robot.core_desire}。这是我的新声音。`)}&robot_id=${robot.id}&_t=${Date.now()}`;
                        el.play().catch(() => {});
                      }
                      // Reset to idle after 4s
                      setTimeout(() => setVoiceRegenState("idle"), 4000);
                    } catch {
                      setVoiceRegenState("idle");
                    }
                  }}
                  className="text-[10px] font-medium text-nomi-rose"
                >换</button>
                <button
                  onClick={() => setVoiceRegenState("idle")}
                  className="text-[10px] text-nomi-charcoal-muted"
                >取消</button>
              </div>
            )}
            {voiceRegenState === "loading" && (
              <div className="flex items-center gap-1.5 rounded-full bg-nomi-warm-gray/20 px-2.5 py-1">
                <div className="nomi-orb h-3 w-3" />
                <span className="text-[10px] text-nomi-charcoal-muted">正在生成新声音...</span>
              </div>
            )}
            {voiceRegenState === "done" && (
              <div className="flex items-center gap-1.5 rounded-full bg-green-50 px-2.5 py-1">
                <span className="text-[10px]">✓</span>
                <span className="text-[10px] text-green-700">{voiceRegenFeel}，试听一下</span>
              </div>
            )}
            <button
              onClick={() => {
                const el = document.getElementById("voice-sample") as HTMLAudioElement;
                if (el) { el.src = `/api/tts/speak?text=${encodeURIComponent(`你好，我是${robot.name}。${robot.core_desire}。这就是我的声音。`)}&robot_id=${robot.id}`; el.play().catch(() => {}); }
              }}
              className="flex h-9 w-9 items-center justify-center rounded-full bg-nomi-rose-light active:scale-95 transition-transform"
            >🔊</button>
          </div>
        </div>

        {/* Personality */}
        <div className="mb-3">
          <div className="mb-1.5 flex items-center justify-between">
            <span className="text-[10px] text-nomi-charcoal-muted">性格</span>
            <RegenButton label="重新生成" robotId={robot.id} module="personality" onDone={reload} />
          </div>
          <div className="flex flex-wrap gap-1.5">
            {robot.personality?.map((trait, i) => (
              <span key={typeof trait === "string" ? trait : i} className={`rounded-full px-2.5 py-0.5 text-[11px] font-medium ${TAG_COLORS[i % TAG_COLORS.length]}`}>
                {typeof trait === "string" ? trait : JSON.stringify(trait)}
              </span>
            ))}
          </div>
        </div>

        {/* Desire & Fear */}
        <div className="mb-3 grid grid-cols-2 gap-2 text-xs">
          <div className="rounded-xl bg-nomi-apricot-light/60 p-2.5">
            <p className="mb-0.5 text-[10px] text-nomi-charcoal-muted">愿望</p>
            <p className="text-[12px]">{robot.core_desire}</p>
          </div>
          <div className="rounded-xl bg-nomi-lavender-light/60 p-2.5">
            <p className="mb-0.5 text-[10px] text-nomi-charcoal-muted">恐惧</p>
            <p className="text-[12px]">{robot.core_fear}</p>
          </div>
        </div>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 rounded-full bg-nomi-warm-gray/10 p-1">
        {([["profile", "画像"], ["memories", "记忆"], ["relationships", "关系"], ["skills", "技能"], ["activity", "活动"]] as const).map(([key, label]) => (
          <button
            key={key}
            onClick={() => { setActiveTab(key); if (key === "activity") { setActivityPage(0); loadActivities(0); } if (key === "skills") loadSkills(); }}
            className={`flex-1 rounded-full py-1.5 text-center text-[12px] font-medium transition-all ${activeTab === key ? "bg-white shadow-sm text-nomi-charcoal" : "text-nomi-charcoal-muted"}`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Origin Story */}
      {activeTab === "profile" && (<>

      <div className="glass shadow-nomi rounded-[20px] p-5">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-[10px] text-nomi-charcoal-muted">出生故事</span>
          <RegenButton label="重新生成" robotId={robot.id} module="origin-story" onDone={reload} />
        </div>
        <p className="text-[13px] leading-[1.8] text-nomi-charcoal-soft">{robot.origin_story}</p>
      </div>

      {/* Portrait */}
      {robot.portrait && (() => {
        const p = robot.portrait as Record<string, unknown>;
        const personality_now = p.personality_now as Record<string, unknown> | undefined;
        const inner_world = p.inner_world as Record<string, unknown> | undefined;
        const quirks = p.signature_quirks as string[] | undefined;
        // Gender: from new portrait field (Chinese, e.g. "偏女性，因为...") or fallback to voice_profile
        const genderRaw = (p.gender_feel as string | undefined)
          || robot.voice_profile?.gender_feeling;
        // For new portrait, gender_feel is a full sentence; for old fallback it's an English key
        const genderFeel = genderRaw
          ? (GENDER_LABEL[genderRaw] ?? genderRaw.split("，")[0])
          : null;

        return (<>
          {/* Life sentence + core identity strip */}
          <div className="glass shadow-nomi rounded-[20px] p-5">
            <div className="mb-3 flex items-start justify-between gap-2">
              <div className="min-w-0">
                {p.life_sentence ? (
                  <p className="text-[15px] font-medium text-nomi-charcoal italic leading-snug">
                    &ldquo;{p.life_sentence as string}&rdquo;
                  </p>
                ) : null}
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {genderFeel && (
                    <span className="rounded-full bg-nomi-lavender-light/70 px-2.5 py-0.5 text-[10px] text-nomi-charcoal-soft">
                      {genderFeel.startsWith("偏") || genderFeel.startsWith("中") || genderFeel.startsWith("两")
                        ? genderFeel.split("，")[0].split("，")[0]
                        : genderFeel.split("，")[0]}
                    </span>
                  )}
                  {(personality_now?.traits as string[] | undefined)?.map((t) => (
                    <span key={t} className="rounded-full bg-nomi-cream px-2.5 py-0.5 text-[10px] text-nomi-charcoal-muted">{t}</span>
                  ))}
                </div>
              </div>
              <RegenButton label="重新生成" robotId={robot.id} module="portrait" onDone={reload} />
            </div>

            {/* Appearance */}
            {p.appearance_now ? (
              <p className="mt-1 text-[11px] text-nomi-charcoal-muted italic border-l-2 border-nomi-rose-light/50 pl-3 leading-relaxed">
                {p.appearance_now as string}
              </p>
            ) : null}
          </div>

          {/* Self description */}
          <div className="glass shadow-nomi rounded-[20px] p-5">
            <span className="text-[10px] text-nomi-charcoal-muted">自述</span>
            <p className="mt-2 text-[13px] leading-[1.8] text-nomi-charcoal-soft">{p.current_self_description as string}</p>
          </div>

          {/* Inner world */}
          {inner_world && (
            <div className="glass shadow-nomi rounded-[20px] p-5">
              <span className="text-[10px] text-nomi-charcoal-muted">内心世界</span>
              <div className="mt-2 space-y-2.5">
                {([
                  ["珍视", inner_world.what_it_values, "bg-nomi-rose-pale"],
                  ["恐惧", inner_world.what_it_fears_now, "bg-nomi-lavender-light/60"],
                  ["放不下", inner_world.unresolved, "bg-nomi-apricot-light/60"],
                  ["领悟", inner_world.wisdom, "bg-nomi-sage-light/60"],
                ] as [string, unknown, string][]).map(([label, value, bg]) => value ? (
                  <div key={label} className={`rounded-xl ${bg} p-2.5`}>
                    <p className="mb-0.5 text-[10px] text-nomi-charcoal-muted">{label}</p>
                    <p className="text-[12px]">{value as string}</p>
                  </div>
                ) : null)}
              </div>
            </div>
          )}

          {/* Remembered facts & faded impressions */}
          {((p.remembered_facts as string[])?.length > 0 || (p.faded_impressions as string[])?.length > 0) && (
            <div className="glass shadow-nomi rounded-[20px] p-5">
              <span className="text-[10px] text-nomi-charcoal-muted">记忆痕迹</span>
              {(p.remembered_facts as string[])?.length > 0 && (
                <div className="mt-2">
                  <p className="mb-1 text-[10px] font-medium text-nomi-charcoal-soft">还记得的事</p>
                  <ul className="space-y-1">
                    {(p.remembered_facts as string[]).map((f, i) => (
                      <li key={i} className="text-[12px] text-nomi-charcoal-soft">· {f}</li>
                    ))}
                  </ul>
                </div>
              )}
              {(p.faded_impressions as string[])?.length > 0 && (
                <div className="mt-3">
                  <p className="mb-1 text-[10px] font-medium text-nomi-charcoal-muted">模糊的印象</p>
                  <ul className="space-y-1 opacity-60">
                    {(p.faded_impressions as string[]).map((f, i) => (
                      <li key={i} className="text-[12px] italic text-nomi-charcoal-muted">· {f}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          {/* How it speaks + quirks */}
          {(personality_now?.how_it_speaks || (quirks?.length ?? 0) > 0) ? (
            <div className="glass shadow-nomi rounded-[20px] p-5">
              <span className="text-[10px] text-nomi-charcoal-muted">说话方式 &amp; 小习惯</span>
              {personality_now?.how_it_speaks ? (
                <p className="mt-1.5 text-[12px] text-nomi-charcoal-soft">{personality_now.how_it_speaks as string}</p>
              ) : null}
              {personality_now?.emotional_baseline ? (
                <span className="mt-2 inline-block rounded-full bg-nomi-cream px-2.5 py-0.5 text-[10px] text-nomi-charcoal-muted">情绪基调：{personality_now.emotional_baseline as string}</span>
              ) : null}
              {quirks && quirks.length > 0 ? (
                <ul className="mt-2.5 space-y-1">
                  {quirks.map((q, i) => (
                    <li key={i} className="flex items-start gap-1.5 text-[11px] text-nomi-charcoal-muted">
                      <span className="shrink-0 opacity-50">✦</span>{q}
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}

          {/* Triggers */}
          {(() => {
            const triggers = personality_now?.triggers as string[] | undefined;
            return triggers && triggers.length > 0 ? (
              <div className="glass shadow-nomi rounded-[20px] p-5">
                <span className="text-[10px] text-nomi-charcoal-muted">会触动它的事</span>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {triggers.map((t, i) => (
                    <span key={i} className="rounded-full bg-nomi-apricot-light/60 px-2.5 py-1 text-[11px] text-nomi-charcoal-soft">{t}</span>
                  ))}
                </div>
              </div>
            ) : null;
          })()}
        </>);
      })()}

      </>)}

      {/* Relationships tab */}
      {activeTab === "relationships" && (
        <div className="glass shadow-nomi rounded-[20px] p-5">
          <span className="text-[10px] text-nomi-charcoal-muted">关系</span>
          {(robot.relationships_snapshot as { name: string; role: string; status: string; memories: string[] }[] | null)?.length ? (
            <div className="mt-2 space-y-2">
              {(robot.relationships_snapshot as { name: string; role: string; status: string; memories: string[] }[]).map((rel) => {
                const isExpanded = expandedId === `rel-${rel.name}`;
                return (
                  <div key={rel.name} className="rounded-xl bg-white/50">
                    <button onClick={() => setExpandedId(isExpanded ? null : `rel-${rel.name}`)} className="flex w-full items-center gap-2 p-2.5 text-left">
                      <span className="text-[13px]">{rel.status === "已离开" ? "👤" : "💛"}</span>
                      <div className="min-w-0 flex-1">
                        <span className="text-[12px] font-medium">{rel.name}</span>
                        <span className="ml-1.5 text-[10px] text-nomi-charcoal-muted">{rel.role}</span>
                      </div>
                      <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] ${rel.status === "已离开" ? "bg-gray-100 text-gray-400" : rel.status === "亲密" ? "bg-nomi-rose-pale text-nomi-charcoal-soft" : "bg-nomi-cream text-nomi-charcoal-muted"}`}>
                        {rel.status}
                      </span>
                    </button>
                    {isExpanded && rel.memories?.length > 0 && (
                      <div className="border-t border-nomi-cream/50 px-3 pb-3">
                        <div className="ml-1 mt-2 space-y-1.5 border-l-2 border-nomi-rose-light/40 pl-3">
                          {rel.memories.map((m, i) => (
                            <p key={i} className="text-[11px] leading-relaxed text-nomi-charcoal-soft">{m}</p>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          ) : (
            <p className="mt-4 text-center text-[12px] text-nomi-charcoal-muted py-4">还没有关系记录</p>
          )}
        </div>
      )}

      {/* Memories tab */}
      {activeTab === "memories" && ages.length > 0 && (
        <div className="glass shadow-nomi rounded-[20px] p-5">
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-nomi-charcoal-muted">记忆</span>
            <RegenButton label="重新生成" robotId={robot.id} module="memories" onDone={reload} />
          </div>
          <div className="mt-3 space-y-3">
            {ages.map((age) => {
              const mems = memsByAge.get(age)!;
              return (
                <div key={age}>
                  <div className="mb-1.5 flex items-center gap-2">
                    <div className="flex h-6 w-6 items-center justify-center rounded-full bg-nomi-rose-light text-[10px] font-bold text-nomi-charcoal">{age}</div>
                    <span className="text-[10px] text-nomi-charcoal-muted">{age}岁</span>
                  </div>
                  <div className="ml-3 space-y-1.5 border-l border-nomi-rose-light/40 pl-3">
                    {mems.map((mem) => {
                      const strength = mem.memory_strength ?? 1;
                      const pct = Math.round(strength * 100);
                      const isExpanded = expandedId === mem.id;
                      return (
                        <div key={mem.id} className="rounded-xl bg-white/50" style={{ opacity: 0.3 + strength * 0.7 }}>
                          <button onClick={() => setExpandedId(isExpanded ? null : mem.id)} className="flex w-full items-center gap-2 p-2.5 text-left">
                            <p className="min-w-0 flex-1 text-[12px] font-medium">{mem.memory_title}</p>
                            <span className="shrink-0 text-[10px] text-nomi-charcoal-muted">{pct}%</span>
                          </button>
                          {isExpanded && (
                            <div className="border-t border-nomi-cream/50 px-3 pb-3">
                              <p className="whitespace-pre-wrap pt-2 text-[12px] leading-[1.8] text-nomi-charcoal-soft">{mem.memory_content}</p>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Skills tab */}
      {activeTab === "skills" && (
        <div className="glass shadow-nomi rounded-[20px] p-5">
          <div className="mb-3 flex items-center justify-between">
            <span className="text-[10px] text-nomi-charcoal-muted">已习得的技能</span>
            <button onClick={loadSkills} className="text-[10px] text-nomi-charcoal-muted active:text-nomi-charcoal">🔄 刷新</button>
          </div>
          {skills.length === 0 ? (
            <div className="py-8 text-center">
              <p className="text-[12px] text-nomi-charcoal-muted">还没有习得任何技能</p>
              <p className="mt-1 text-[11px] text-nomi-charcoal-muted opacity-60">深度反思后可能触发技能觉醒</p>
            </div>
          ) : (
            <div className="space-y-3">
              {skills.map((s) => {
                const typeIcons: Record<string, string> = { creative: "🎨", knowledge: "📖", social: "💬", search: "🔍", physical: "🤸" };
                const typeColors: Record<string, string> = { creative: "bg-rose-50 text-rose-600", knowledge: "bg-blue-50 text-blue-600", social: "bg-amber-50 text-amber-600", search: "bg-green-50 text-green-600", physical: "bg-purple-50 text-purple-600" };
                return (
                  <div key={s.id} className="rounded-[14px] border border-violet-100 bg-violet-50/40 p-3">
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className="text-base">{typeIcons[s.skill_type || ""] || "⚡"}</span>
                        <span className="font-semibold text-[13px] text-nomi-charcoal">{s.name}</span>
                        {s.skill_type && (
                          <span className={`rounded-full px-1.5 py-0.5 text-[9px] font-medium ${typeColors[s.skill_type] || "bg-stone-100 text-stone-500"}`}>{s.skill_type}</span>
                        )}
                      </div>
                      <span className="shrink-0 text-[10px] text-nomi-charcoal-muted">用了 {s.usage_count} 次</span>
                    </div>
                    {s.description && (
                      <p className="mt-1.5 text-[11px] text-nomi-charcoal-soft leading-relaxed">{s.description}</p>
                    )}
                    {s.trigger_keywords.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1">
                        {s.trigger_keywords.map((kw) => (
                          <span key={kw} className="rounded-full bg-white/80 px-2 py-0.5 text-[10px] text-nomi-charcoal-muted border border-violet-100">{kw}</span>
                        ))}
                      </div>
                    )}
                    {s.acquired_at && (
                      <p className="mt-1.5 text-[9px] text-nomi-charcoal-muted">
                        习得于 {new Date(s.acquired_at).toLocaleString("zh-CN", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                      </p>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Activity tab */}
      {activeTab === "activity" && (
        <div className="rounded-[20px] overflow-hidden">
          <div className="flex items-center justify-between px-1 pb-3">
            <span className="text-[10px] tracking-widest text-nomi-charcoal-muted uppercase">意识流</span>
            <button onClick={() => loadActivities(activityPage)} className="text-[10px] text-nomi-charcoal-muted active:text-nomi-charcoal transition-opacity">刷新</button>
          </div>
          {/* Debug triggers */}
          <div className="mb-4 flex flex-wrap gap-1.5">
            {([
              { key: "thought", label: "生成想法", icon: "💭" },
              { key: "search",  label: "触发搜索", icon: "🔍" },
              { key: "reflect", label: "触发反思", icon: "🪞" },
              { key: "skill",   label: "生成技能", icon: "🌱" },
            ] as const).map(({ key, label, icon }) => {
              const st = triggerState[key] || "idle";
              return (
                <button
                  key={key}
                  disabled={st === "loading"}
                  onClick={() => triggerAction(key)}
                  className={`flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[11px] font-medium transition-all border
                    ${st === "done"    ? "border-green-200 bg-green-50 text-green-600" :
                      st === "error"   ? "border-red-200 bg-red-50 text-red-500" :
                      st === "loading" ? "border-nomi-warm-gray/40 bg-nomi-warm-gray/10 text-nomi-charcoal-muted" :
                                         "border-nomi-warm-gray/30 bg-white/60 text-nomi-charcoal-soft active:scale-95 hover:bg-white/90"}`}
                >
                  {st === "loading"
                    ? <span className="inline-block h-3 w-3 rounded-full border-2 border-nomi-charcoal-muted border-t-transparent animate-spin" />
                    : <span>{icon}</span>
                  }
                  <span>{st === "loading" ? "执行中…" : st === "done" ? "完成 ✓" : st === "error" ? "失败" : label}</span>
                </button>
              );
            })}
          </div>
          {activities.length === 0 ? (
            <div className="glass shadow-nomi rounded-[20px] p-8 text-center">
              <p className="text-[12px] text-nomi-charcoal-muted">唤醒后，这里会出现它的意识轨迹</p>
            </div>
          ) : (
            <div className="relative space-y-2.5">
              {/* Timeline line */}
              <div className="absolute left-[18px] top-3 bottom-16 w-px bg-gradient-to-b from-nomi-rose-light/60 via-nomi-warm-gray/30 to-transparent" />

              {activities.map((a) => {
                const ts = new Date(a.created_at).toLocaleString("zh-CN", { hour: "2-digit", minute: "2-digit" });
                const d = a.detail as Record<string, unknown> | null;

                /* ── THOUGHT ── floating italic quote */
                if (a.event_type === "thought") return (
                  <div key={a.id} className="flex gap-3 items-start">
                    <div className="relative z-10 mt-1 shrink-0 w-9 h-9 rounded-full bg-gradient-to-br from-amber-100 to-orange-100 border border-amber-200/60 flex items-center justify-center shadow-sm">
                      <span className="text-[14px]">💭</span>
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="rounded-[14px] rounded-tl-[4px] bg-gradient-to-br from-amber-50/90 to-orange-50/60 border border-amber-100/80 px-3.5 py-2.5 shadow-sm">
                        <p className="text-[12px] leading-relaxed text-amber-900/80 italic">{a.content}</p>
                      </div>
                      <p className="mt-1 pl-1 text-[9px] text-nomi-charcoal-muted">{ts}</p>
                    </div>
                  </div>
                );

                /* ── CHAT ── speech bubble with target */
                if (a.event_type === "chat" || a.event_type === "speak") return (
                  <div key={a.id} className="flex gap-3 items-start">
                    <div className="relative z-10 mt-1 shrink-0 w-9 h-9 rounded-full bg-gradient-to-br from-sky-100 to-blue-100 border border-sky-200/60 flex items-center justify-center shadow-sm">
                      <span className="text-[14px]">🗣</span>
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="rounded-[14px] rounded-tl-[4px] bg-white/70 border border-sky-100/80 px-3.5 py-2.5 shadow-sm">
                        <p className="text-[12px] leading-relaxed text-nomi-charcoal">{a.content}</p>
                        {d && (d.target as string) && (
                          <div className="mt-1.5 flex items-center gap-1">
                            <span className="text-[9px] text-sky-400">→</span>
                            <span className="text-[10px] text-sky-500 font-medium">{d.target as string}</span>
                          </div>
                        )}
                      </div>
                      <p className="mt-1 pl-1 text-[9px] text-nomi-charcoal-muted">{ts}</p>
                    </div>
                  </div>
                );

                /* ── SEARCH + LEARN ── research card */
                if (a.event_type === "search" || a.event_type === "learn") return (
                  <div key={a.id} className="flex gap-3 items-start">
                    <div className="relative z-10 mt-1 shrink-0 w-9 h-9 rounded-full bg-gradient-to-br from-teal-100 to-emerald-100 border border-teal-200/60 flex items-center justify-center shadow-sm">
                      <span className="text-[14px]">{a.event_type === "search" ? "🔍" : "📖"}</span>
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="rounded-[14px] rounded-tl-[4px] bg-gradient-to-br from-teal-50/80 to-emerald-50/50 border border-teal-100/80 px-3.5 py-2.5 shadow-sm">
                        <p className="text-[11px] text-teal-700/70 mb-1">{a.event_type === "search" ? "正在探索" : "学到了"}</p>
                        <p className="text-[12px] leading-relaxed text-teal-900">{a.content}</p>
                        {d && (d.key_facts as string[]) && ((d.key_facts as string[]).length > 0) && (
                          <div className="mt-2 space-y-1">
                            {(d.key_facts as string[]).slice(0, 3).map((f, i) => (
                              <div key={i} className="flex items-start gap-1.5">
                                <span className="mt-0.5 shrink-0 w-1 h-1 rounded-full bg-teal-400" />
                                <p className="text-[10px] text-teal-700">{f}</p>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                      <p className="mt-1 pl-1 text-[9px] text-nomi-charcoal-muted">{ts}</p>
                    </div>
                  </div>
                );

                /* ── REFLECT ── mirror card */
                if (a.event_type === "reflect") return (
                  <div key={a.id} className="flex gap-3 items-start">
                    <div className="relative z-10 mt-1 shrink-0 w-9 h-9 rounded-full bg-gradient-to-br from-slate-100 to-gray-100 border border-slate-200/60 flex items-center justify-center shadow-sm">
                      <span className="text-[14px]">🪞</span>
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="rounded-[14px] rounded-tl-[4px] bg-gradient-to-br from-slate-50/90 to-gray-50/60 border border-slate-100/80 px-3.5 py-2.5 shadow-sm">
                        <p className="text-[11px] text-slate-500/70 mb-1">自我审视</p>
                        <p className="text-[12px] leading-relaxed text-slate-600 italic">{a.content}</p>
                      </div>
                      <p className="mt-1 pl-1 text-[9px] text-nomi-charcoal-muted">{ts}</p>
                    </div>
                  </div>
                );

                /* ── SKILL ACQUIRED ── achievement badge */
                if (a.event_type === "skill_acquired") return (
                  <div key={a.id} className="flex gap-3 items-start">
                    <div className="relative z-10 mt-1 shrink-0 w-9 h-9 rounded-full bg-gradient-to-br from-violet-100 to-purple-100 border border-violet-200/60 flex items-center justify-center shadow-sm">
                      <span className="text-[14px]">🌱</span>
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="rounded-[14px] rounded-tl-[4px] bg-gradient-to-br from-violet-50/90 to-purple-50/60 border border-violet-100/80 px-3.5 py-2.5 shadow-sm">
                        <p className="text-[11px] text-violet-500/70 mb-1">习得新技能</p>
                        <p className="text-[12px] font-medium text-violet-800">{a.content}</p>
                        {d && (d.description as string) && (
                          <p className="mt-1 text-[10px] text-violet-600/80">{d.description as string}</p>
                        )}
                      </div>
                      <p className="mt-1 pl-1 text-[9px] text-nomi-charcoal-muted">{ts}</p>
                    </div>
                  </div>
                );

                /* ── SKILL USED ── usage pill */
                if (a.event_type === "skill_used") return (
                  <div key={a.id} className="flex gap-3 items-start">
                    <div className="relative z-10 mt-1 shrink-0 w-9 h-9 rounded-full bg-gradient-to-br from-indigo-100 to-blue-100 border border-indigo-200/60 flex items-center justify-center shadow-sm">
                      <span className="text-[14px]">⚡</span>
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="rounded-[14px] rounded-tl-[4px] bg-gradient-to-br from-indigo-50/80 to-blue-50/50 border border-indigo-100/80 px-3.5 py-2.5 shadow-sm">
                        <p className="text-[12px] leading-relaxed text-indigo-800">{a.content}</p>
                        {d && (d.skill as string) && (
                          <span className="mt-1.5 inline-block rounded-full bg-indigo-100 px-2 py-0.5 text-[10px] text-indigo-600">
                            {d.skill as string}
                          </span>
                        )}
                      </div>
                      <p className="mt-1 pl-1 text-[9px] text-nomi-charcoal-muted">{ts}</p>
                    </div>
                  </div>
                );

                /* ── EVOLVE ── milestone */
                if (a.event_type === "evolve") return (
                  <div key={a.id} className="flex gap-3 items-start">
                    <div className="relative z-10 mt-1 shrink-0 w-9 h-9 rounded-full bg-gradient-to-br from-rose-100 to-pink-100 border border-rose-200/60 flex items-center justify-center shadow-sm">
                      <span className="text-[14px]">✨</span>
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="rounded-[14px] rounded-tl-[4px] bg-gradient-to-br from-rose-50/90 to-pink-50/60 border border-rose-100/80 px-3.5 py-2.5 shadow-sm">
                        <p className="text-[11px] text-rose-400/70 mb-1">成长时刻</p>
                        <p className="text-[12px] leading-relaxed text-rose-800">{a.content}</p>
                      </div>
                      <p className="mt-1 pl-1 text-[9px] text-nomi-charcoal-muted">{ts}</p>
                    </div>
                  </div>
                );

                /* ── DEFAULT ── */
                return (
                  <div key={a.id} className="flex gap-3 items-start">
                    <div className="relative z-10 mt-1 shrink-0 w-9 h-9 rounded-full bg-nomi-warm-gray/30 border border-nomi-warm-gray/20 flex items-center justify-center">
                      <span className="text-[12px] text-nomi-charcoal-muted">·</span>
                    </div>
                    <div className="flex-1 min-w-0 pt-1.5">
                      <p className="text-[12px] leading-relaxed text-nomi-charcoal-soft">{a.content}</p>
                      <p className="mt-1 text-[9px] text-nomi-charcoal-muted">{ts}</p>
                    </div>
                  </div>
                );
              })}

              {/* Pagination */}
              {activityTotal > ACTIVITY_PAGE_SIZE && (
                <div className="flex items-center justify-between pt-2 pl-12">
                  <button
                    disabled={activityPage === 0}
                    onClick={() => { const p = activityPage - 1; setActivityPage(p); loadActivities(p); }}
                    className="rounded-full border border-nomi-warm-gray/30 px-3 py-1 text-[11px] text-nomi-charcoal-muted disabled:opacity-30 active:bg-nomi-warm-gray/10"
                  >← 更新</button>
                  <span className="text-[10px] text-nomi-charcoal-muted">
                    {activityPage * ACTIVITY_PAGE_SIZE + 1}–{Math.min((activityPage + 1) * ACTIVITY_PAGE_SIZE, activityTotal)} / {activityTotal}
                  </span>
                  <button
                    disabled={(activityPage + 1) * ACTIVITY_PAGE_SIZE >= activityTotal}
                    onClick={() => { const p = activityPage + 1; setActivityPage(p); loadActivities(p); }}
                    className="rounded-full border border-nomi-warm-gray/30 px-3 py-1 text-[11px] text-nomi-charcoal-muted disabled:opacity-30 active:bg-nomi-warm-gray/10"
                  >更早 →</button>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      <audio id="voice-sample" playsInline style={{ display: "none" }} />

      {/* Actions */}
      <div className="flex gap-2 pb-8">
        <button onClick={() => router.push(`/chat?robot=${robot.id}`)} className="flex-1 rounded-full bg-nomi-rose py-2.5 text-sm font-medium text-white shadow-nomi">
          单聊
        </button>
        <button onClick={() => router.push("/chat")} className="flex-1 rounded-full bg-nomi-lavender-light py-2.5 text-sm font-medium text-nomi-charcoal shadow-nomi">
          群聊
        </button>
        <button
          onClick={async () => {
            if (!confirm(`确定要删除 ${robot.name} 吗？无法恢复。`)) return;
            if (!confirm(`再次确认：真的要让 ${robot.name} 消失吗？`)) return;
            await fetch(`/api/robots/${robot.id}`, { method: "DELETE" });
            router.push("/");
          }}
          className="shrink-0 rounded-full border border-red-200 px-3 py-2.5 text-[11px] text-red-400 active:bg-red-50"
        >
          删除
        </button>
      </div>
    </div>
  );
}
