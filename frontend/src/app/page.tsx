"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { Robot } from "@/lib/types";
import RobotCard from "@/app/components/RobotCard";

interface Step {
  id: string;
  label: string;
  status: "pending" | "running" | "done";
  detail?: string;
}

interface CreationJob {
  status: string;
  steps: Step[];
  robot: Record<string, unknown> | null;
  portrait: Record<string, unknown> | null;
  stats: Record<string, unknown> | null;
  error: string | null;
  memories_done: number;
  memories_total: number;
  current_memory: string | null;
  total_words: number;
}

export default function HomePage() {
  const router = useRouter();
  const [robots, setRobots] = useState<Robot[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);
  const [textHint, setTextHint] = useState("");
  const [preview, setPreview] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Creation progress
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<CreationJob | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.listRobots().then(setRobots).catch(console.error).finally(() => setLoading(false));
  }, []);

  // Poll for job status
  useEffect(() => {
    if (!jobId) return;
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`/api/robots/creation-status/${jobId}`);
        if (!res.ok) return;
        const data: CreationJob = await res.json();
        setJob(data);

        if (data.status === "done" || data.status === "error") {
          clearInterval(interval);
          if (data.status === "done") {
            // Refresh robot list
            api.listRobots().then(setRobots).catch(console.error);
          }
        }
      } catch (e) {
        console.error(e);
      }
    }, 1500);
    return () => clearInterval(interval);
  }, [jobId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [job]);

  const handleDelete = async (id: string) => {
    if (deleteConfirm !== id) { setDeleteConfirm(id); return; }
    setDeleteConfirm(null);
    try {
      await api.deleteRobot(id);
      setRobots((prev) => prev.filter((r) => r.id !== id));
    } catch (err) {
      console.error(err);
    }
  };

  const reset = () => {
    setShowCreate(false); setSubmitting(false); setJobId(null); setJob(null);
    setSelectedFile(null); setPreview(null); setTextHint("");
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setSelectedFile(file);
    const reader = new FileReader();
    reader.onload = (ev) => setPreview(ev.target?.result as string);
    reader.readAsDataURL(file);
  };

  const handleCreate = async () => {
    if ((!selectedFile && !textHint.trim()) || submitting) return;
    setSubmitting(true);
    try {
      const form = new FormData();
      if (selectedFile) form.append("image", selectedFile);
      if (textHint.trim()) form.append("text_hint", textHint.trim());

      const res = await fetch("/api/robots/from-image", {
        method: "POST",
        body: form,
      });
      if (!res.ok) throw new Error(`API error: ${res.status}`);
      const data = await res.json();
      setJobId(data.job_id);
    } catch (err) {
      console.error(err);
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="flex min-h-[70vh] flex-col items-center justify-center gap-4">
        <div className="nomi-orb h-16 w-16" />
        <p className="text-sm tracking-wide text-nomi-charcoal-muted">正在寻找小生命们...</p>
      </div>
    );
  }

  // === Upload Form ===
  if ((robots.length === 0 || showCreate) && !jobId) {
    return (
      <div className="animate-fade-up">
        {robots.length > 0 && (
          <button onClick={reset} className="mb-6 text-sm text-nomi-charcoal-muted hover:text-nomi-charcoal transition-colors">← 回到房间</button>
        )}
        <div className="mb-8 flex flex-col items-center text-center">
          <div className="nomi-orb mb-6 h-20 w-20 shadow-nomi" />
          <h1 className="mb-1 text-[22px] font-semibold tracking-[0.15em]">{robots.length === 0 ? "NOMI" : "新的小生命"}</h1>
          {robots.length === 0 && <p className="mb-1 text-[11px] tracking-[0.3em] text-nomi-charcoal-muted">MEMORY. WARMTH. WITH YOU.</p>}
          <p className="mt-3 text-sm text-nomi-charcoal-soft">拍一张身边物品的照片<br />我来想象它的一生</p>
        </div>
        <div onClick={() => fileInputRef.current?.click()} className="glass shadow-nomi mb-4 flex min-h-[200px] cursor-pointer items-center justify-center overflow-hidden rounded-[24px] transition-all duration-300 hover:shadow-lg">
          {preview
            ? <img src={preview} alt="预览" className="h-full max-h-[280px] w-full object-contain p-2" />
            : <div className="flex flex-col items-center gap-3 p-10">
                <div className="flex h-14 w-14 items-center justify-center rounded-full bg-nomi-apricot-light">
                  <svg className="h-6 w-6 text-nomi-charcoal-soft" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6.827 6.175A2.31 2.31 0 015.186 7.23c-.38.054-.757.112-1.134.175C2.999 7.58 2.25 8.507 2.25 9.574V18a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9.574c0-1.067-.75-1.994-1.802-2.169a47.865 47.865 0 00-1.134-.175 2.31 2.31 0 01-1.64-1.055l-.822-1.316a2.192 2.192 0 00-1.736-1.039 48.774 48.774 0 00-5.232 0 2.192 2.192 0 00-1.736 1.039l-.821 1.316z" />
                    <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 12.75a4.5 4.5 0 11-9 0 4.5 4.5 0 019 0z" />
                  </svg>
                </div>
                <p className="text-sm text-nomi-charcoal-muted">点击上传物品照片</p>
              </div>
          }
        </div>
        <input ref={fileInputRef} type="file" accept="image/*" onChange={handleFileSelect} className="hidden" />
        <textarea value={textHint} onChange={(e) => setTextHint(e.target.value)} placeholder="补充描述（可选）：比如这个杯子陪了我五年了..." rows={2} className="glass mb-5 w-full rounded-[16px] p-4 text-sm placeholder:text-nomi-charcoal-muted focus:outline-none focus:ring-2 focus:ring-nomi-rose-light" />
        <button onClick={handleCreate} disabled={(!selectedFile && !textHint.trim()) || submitting} className="w-full rounded-full bg-gradient-to-r from-nomi-rose to-nomi-apricot py-3.5 text-sm font-semibold tracking-wide text-white shadow-nomi transition-all hover:shadow-lg disabled:opacity-40">
          {submitting ? "提交中..." : "赋予它生命"}
        </button>
        {!selectedFile && <p className="mt-4 text-center text-xs text-nomi-charcoal-muted">没有图片？直接写物品描述也可以</p>}
      </div>
    );
  }

  // === Creation Progress ===
  if (jobId && job) {
    return (
      <div className="space-y-5 animate-fade-up">
        {preview && (
          <div className="flex justify-center">
            <div className="overflow-hidden rounded-2xl shadow-nomi">
              <img src={preview} alt="物品" className="h-24 w-24 object-cover" />
            </div>
          </div>
        )}

        {/* Steps checklist */}
        <div className="glass-strong shadow-nomi rounded-[20px] p-5">
          <div className="space-y-4">
            {job.steps.map((step: Step & { time_ms?: number; cost_usd?: number; provider?: string }) => (
              <div key={step.id} className="flex items-start gap-3">
                <div className="mt-0.5 shrink-0">
                  {step.status === "done" && <span className="text-base">✅</span>}
                  {step.status === "running" && <div className="nomi-orb h-5 w-5" />}
                  {step.status === "pending" && <span className="inline-block h-5 w-5 rounded-full border-2 border-nomi-warm-gray/30" />}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <p className={`text-[13px] ${step.status === "running" ? "font-semibold" : step.status === "done" ? "text-nomi-charcoal-soft" : "text-nomi-charcoal-muted"}`}>
                      {step.label}
                    </p>
                    {/* Time & cost badges */}
                    {step.status === "done" && (step.time_ms || step.cost_usd) && (
                      <div className="flex shrink-0 items-center gap-1.5">
                        {step.time_ms ? (
                          <span className="rounded bg-nomi-apricot-light/80 px-1.5 py-0.5 text-[10px] text-nomi-charcoal-muted">
                            {step.time_ms >= 1000 ? `${(step.time_ms / 1000).toFixed(1)}s` : `${step.time_ms}ms`}
                          </span>
                        ) : null}
                        {step.cost_usd ? (
                          <span className="rounded bg-nomi-lavender-light/80 px-1.5 py-0.5 text-[10px] text-nomi-charcoal-muted">
                            ${step.cost_usd.toFixed(3)}
                          </span>
                        ) : null}
                        {step.provider ? (
                          <span className="rounded bg-nomi-sage-light/80 px-1.5 py-0.5 text-[10px] text-nomi-charcoal-muted">
                            {step.provider}
                          </span>
                        ) : null}
                      </div>
                    )}
                  </div>
                  {step.detail && (
                    <p className="mt-0.5 text-xs text-nomi-charcoal-muted">{step.detail}</p>
                  )}
                  {/* Memory sub-progress */}
                  {step.id === "memories" && step.status === "running" && job.memories_total > 0 && (
                    <div className="mt-2">
                      <div className="mb-1 flex justify-between text-[11px] text-nomi-charcoal-muted">
                        <span>{job.current_memory ? `${job.current_memory}` : "准备中..."}</span>
                        <span>{job.memories_done}/{job.memories_total}</span>
                      </div>
                      <div className="h-1.5 overflow-hidden rounded-full bg-nomi-rose-pale">
                        <div className="memory-line h-full transition-all duration-500" style={{ width: `${(job.memories_done / job.memories_total) * 100}%` }} />
                      </div>
                      {job.total_words > 0 && (
                        <p className="mt-1 text-[10px] text-nomi-charcoal-muted">{job.total_words.toLocaleString()} 字</p>
                      )}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Robot info (once personality is done) */}
        {job.robot && (
          <div className="glass shadow-nomi rounded-[20px] p-5 animate-fade-up">
            <div className="mb-2 flex items-center gap-3">
              <div className="nomi-orb h-10 w-10 shrink-0" />
              <div>
                <h2 className="text-lg font-semibold tracking-wide">{job.robot.name as string}</h2>
                <p className="text-xs text-nomi-charcoal-muted">{job.robot.age as number}岁 · {job.robot.birth_place as string}</p>
              </div>
            </div>
            <div className="mb-2 flex flex-wrap gap-1.5">
              {(job.robot.personality as string[] || []).map((t) => (
                <span key={t} className="rounded-full bg-nomi-rose-pale px-2.5 py-0.5 text-[11px] font-medium">{t}</span>
              ))}
            </div>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div className="rounded-[12px] bg-nomi-apricot-light/60 p-2.5">
                <span className="text-nomi-charcoal-muted">愿望</span>
                <p className="mt-0.5 font-medium">{job.robot.core_desire as string}</p>
              </div>
              <div className="rounded-[12px] bg-nomi-lavender-light/60 p-2.5">
                <span className="text-nomi-charcoal-muted">恐惧</span>
                <p className="mt-0.5 font-medium">{job.robot.core_fear as string}</p>
              </div>
            </div>
          </div>
        )}

        {/* Error */}
        {job.status === "error" && (
          <div className="glass rounded-[16px] border border-red-200 p-4">
            <p className="text-sm font-medium text-red-600">出错了</p>
            <p className="mt-1 text-xs text-red-400">{job.error}</p>
            <div className="mt-3 flex gap-2">
              <button onClick={reset} className="rounded-full bg-red-50 px-4 py-1.5 text-xs text-red-600">重试</button>
              {(job as CreationJob & { robot_db_id?: string }).robot_db_id && (
                <button onClick={() => router.push(`/robots/${(job as CreationJob & { robot_db_id?: string }).robot_db_id}`)} className="rounded-full bg-nomi-cream px-4 py-1.5 text-xs text-nomi-charcoal-soft">查看已创建部分</button>
              )}
            </div>
          </div>
        )}

        {/* Done */}
        {job.status === "done" && (
          <div className="space-y-4 animate-fade-up">
            <div className="glass-strong shadow-nomi rounded-[20px] p-5 text-center">
              <div className="nomi-orb mx-auto mb-3 h-10 w-10" />
              <p className="text-sm font-semibold">{job.robot?.name as string} 的记忆已经成形</p>
              <p className="mt-1 text-[11px] text-nomi-charcoal-muted">
                {job.memories_total} 条记忆 · {job.total_words.toLocaleString()} 字
              </p>
            </div>
            {job.stats && (
              <div className="flex justify-center gap-4 text-[10px] text-nomi-charcoal-muted">
                <span>{((job.stats.total_time_ms as number) / 1000).toFixed(0)}s</span>
                <span>${(job.stats.total_cost_usd as number).toFixed(2)}</span>
              </div>
            )}
            <button onClick={() => { reset(); }} className="w-full rounded-full bg-gradient-to-r from-nomi-rose to-nomi-apricot py-3.5 text-sm font-semibold tracking-wide text-white shadow-nomi">
              回到房间
            </button>
          </div>
        )}

        <div ref={bottomRef} />
      </div>
    );
  }

  // === Waiting for job to start ===
  if (jobId && !job) {
    return (
      <div className="flex min-h-[50vh] flex-col items-center justify-center gap-4">
        <div className="nomi-orb h-12 w-12" />
        <p className="text-sm text-nomi-charcoal-muted">正在启动...</p>
      </div>
    );
  }

  // === Robot List ===
  return (
    <div className="animate-fade-up">
      <div className="mb-8 flex flex-col items-center">
        <div className="nomi-orb mb-3 h-12 w-12" />
        <h1 className="text-[11px] tracking-[0.3em] text-nomi-charcoal-muted">NOMI</h1>
      </div>
      <div className="stagger-children mb-8 flex flex-col gap-3">
        {robots.map((robot, i) => (
          <div key={robot.id}>
            <RobotCard robot={robot} index={i} onDelete={handleDelete} />
            {deleteConfirm === robot.id && (
              <div className="mt-1 flex items-center justify-end gap-2 px-2 text-xs">
                <span className="text-nomi-charcoal-muted">确认删除 {robot.name}？</span>
                <button onClick={() => handleDelete(robot.id)} className="rounded-full bg-red-50 px-3 py-1 text-red-500 hover:bg-red-100">确认</button>
                <button onClick={() => setDeleteConfirm(null)} className="rounded-full bg-nomi-cream px-3 py-1 text-nomi-charcoal-soft">取消</button>
              </div>
            )}
          </div>
        ))}
      </div>
      <div className="flex gap-3">
        <button onClick={() => setShowCreate(true)} className="glass shadow-nomi flex-1 rounded-full py-3 text-center text-sm font-medium transition-all hover:shadow-lg">+ 新物品</button>
        <button onClick={() => router.push("/chat")} className="flex-1 rounded-full bg-gradient-to-r from-nomi-rose to-nomi-apricot py-3 text-center text-sm font-medium text-white shadow-nomi">单聊</button>
        <button onClick={() => router.push("/group-chat")} className="glass shadow-nomi flex-1 rounded-full py-3 text-center text-sm font-medium transition-all hover:shadow-lg">群聊</button>
      </div>
      {/* Data management */}
      <div className="flex gap-2 pt-2">
        <button
          onClick={async () => {
            if (!confirm("确认清除所有聊天记录？")) return;
            if (!confirm("再次确认：这会删除所有对话历史，无法恢复")) return;
            await fetch("/api/conversations/all", { method: "DELETE" });
            alert("聊天记录已清除");
          }}
          className="flex-1 rounded-full border border-nomi-warm-gray/30 py-2 text-center text-[11px] text-nomi-charcoal-muted active:bg-red-50 active:text-red-500"
        >
          清除聊天记录
        </button>
        <button
          onClick={async () => {
            if (!confirm("确认清除所有活动日志？")) return;
            if (!confirm("再次确认：这会删除所有活动历史，无法恢复")) return;
            await fetch("/api/robots/activity/all", { method: "DELETE" });
            alert("活动日志已清除");
          }}
          className="flex-1 rounded-full border border-nomi-warm-gray/30 py-2 text-center text-[11px] text-nomi-charcoal-muted active:bg-red-50 active:text-red-500"
        >
          清除活动日志
        </button>
      </div>
    </div>
  );
}
