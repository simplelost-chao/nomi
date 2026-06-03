# Memory Quality Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve memory diversity, add structured relationships with per-relationship memories, show full portrait data, and fix TTS.

**Architecture:** 4 independent improvements: (1) prompt changes for memory diversity + structured relationships in ongoing_state, (2) DB migration for relationships_snapshot + backend wiring, (3) frontend portrait + relationships display, (4) TTS URL fix.

**Tech Stack:** Python/FastAPI, Next.js/React, SQLAlchemy, Alembic

---

### Task 1: Prompt improvements — memory diversity + structured relationships

**Files:**
- Modify: `backend/app/prompts/creation.py`

- [ ] **Step 1: Add event diversity guidance to system prompt**

In `backend/app/prompts/creation.py`, in `build_batch_memories_prompt`, add the following block after the `## 密度变化` section (after line 207 `{ongoing_block}`), before `{prev_block}`:

```python
    diversity_block = f"""
## 一生应该有的经历类型（不是每种都要有，但不能只有一种）

- 环境变化：搬家、换房间、被带出门、旅行、被存进箱子
- 人的变化：换主人、新的家庭成员、客人、小孩、宠物
- 意外事件：摔落、被修补、被误用、丢失又找回、差点被扔掉
- 时代印记：周围物品的更替、声音的变化（收音机→电视→手机）、装修
- 关系时刻：被当礼物送出、被争抢、被分享、被嫉妒、被忽视
- 仪式感：生日、节日、搬新家、告别
- 内心转折：第一次意识到自己老了、接受被遗忘、理解主人的选择

不要让所有记忆都是同一种类型的变体。如果连续 3 条记忆都是"被拿起来用了一下"，
说明你在重复而不是在创造一段人生。一个物品的一生应该跟人一样丰富——
有平静的日常，也有突然的变故；有亲密的陪伴，也有被遗忘的角落。"""
```

Insert `{diversity_block}` into the system prompt string, right after `{ongoing_block}`.

- [ ] **Step 2: Change ongoing_state relationships format in prompt**

In the same function, update the user_msg template. Replace:

```python
    "relationships": ["当前的关系状态"],
```

with:

```python
    "relationships": [
      {{
        "name": "关系对象的名字",
        "role": "主人/家人/朋友/邻居/宠物/陌生人",
        "status": "亲密/熟悉/疏远/已离开/新认识",
        "memories": ["这段关系中的关键时刻（每条一句话，按时间顺序）"]
      }}
    ],
```

- [ ] **Step 3: Add relationships guidance to ongoing_state rules**

In the `ongoing_block` string (the block that appears when `ongoing_state` is not None), append after the existing rules:

```python
    if ongoing_state:
        import json as _json
        ongoing_block = f"""
当前累积状态（你必须在新记忆中保持这些状态的一致性）：
{_json.dumps(ongoing_state, ensure_ascii=False, indent=2)}

规则：
- physical 中的状态只增不减（裂痕不会自己消失，除非有修复事件并在记忆中描述）
- 如果状态发生变化（搬家、换主人、被修复），必须有一条记忆描述这个变化
- 不要凭空出现或消失任何状态
- relationships 中每个关系有 name、role、status、memories
  - 新的互动追加到对应关系的 memories 列表
  - 关系状态可以变化（亲密→疏远→重新亲密）
  - 人/物离开了也要保留，status 标为"已离开"
  - 新出现的人/物创建新的关系条目"""
```

- [ ] **Step 4: Verify prompt compiles**

```bash
cd /Users/chao/projects/nomi/backend && python -c "from app.prompts.creation import build_batch_memories_prompt; print('OK')"
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/prompts/creation.py
git commit -m "feat: add event diversity guidance and structured relationships to memory prompt"
```

---

### Task 2: DB migration + backend wiring for relationships_snapshot

**Files:**
- Modify: `backend/app/db/models.py:38-67` (Robot model)
- Modify: `backend/app/api/robots.py` (save snapshot after generation)
- Modify: `backend/app/api/regenerate.py` (save snapshot after regeneration)
- Modify: `backend/app/schemas.py` (add to RobotOut)
- Create: `backend/alembic/versions/<auto>_add_relationships_snapshot.py`

- [ ] **Step 1: Add field to Robot model**

In `backend/app/db/models.py`, add to the `Robot` class after the `generation_stats` line (line 60):

```python
    generation_stats: Mapped[dict | None] = mapped_column(JSONB)
    relationships_snapshot: Mapped[list | None] = mapped_column(JSONB)
```

- [ ] **Step 2: Add to schema**

In `backend/app/schemas.py`, add to `RobotOut` (after line 57):

```python
    generation_stats: dict | None
    relationships_snapshot: list | None = None
    created_at: datetime
```

And add `portrait` to `RobotDetail`:

```python
class RobotDetail(RobotOut):
    yearly_memories: list[YearlyMemoryOut] = []
    portrait: dict | None = None
```

- [ ] **Step 3: Generate and run migration**

```bash
cd /Users/chao/projects/nomi/backend && python -m alembic revision --autogenerate -m "add relationships_snapshot to robots"
python -m alembic upgrade head
```

- [ ] **Step 4: Save relationships_snapshot in _run_creation**

In `backend/app/api/robots.py`, after the batch generation loop ends (after `_set_step(job, "memories", "done", ...)`), add:

```python
            # Save relationships from final ongoing_state
            robot.relationships_snapshot = ongoing_state.get("relationships", []) if ongoing_state else []
            await session.commit()
```

- [ ] **Step 5: Save relationships_snapshot in regenerate_memories**

In `backend/app/api/regenerate.py`, at the end of `regenerate_memories` before the return, add:

```python
    # Save relationships from final ongoing_state
    robot.relationships_snapshot = ongoing_state.get("relationships", []) if ongoing_state else []
    await session.commit()
```

- [ ] **Step 6: Verify**

```bash
cd /Users/chao/projects/nomi/backend && python -c "import ast; ast.parse(open('app/api/robots.py').read()); ast.parse(open('app/api/regenerate.py').read()); ast.parse(open('app/schemas.py').read()); print('OK')"
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/db/models.py backend/app/schemas.py backend/app/api/robots.py backend/app/api/regenerate.py backend/alembic/versions/*relationships*
git commit -m "feat: add relationships_snapshot field, save after memory generation"
```

---

### Task 3: Frontend — rich portrait display + relationships + TTS fix

**Files:**
- Modify: `frontend/src/app/robots/[id]/page.tsx`
- Modify: `frontend/src/lib/types.ts`

- [ ] **Step 1: Update types**

In `frontend/src/lib/types.ts`, update `Robot` interface — add after `generation_stats`:

```typescript
  relationships_snapshot: {
    name: string;
    role: string;
    status: string;
    memories: string[];
  }[] | null;
```

- [ ] **Step 2: Fix TTS URLs**

In `frontend/src/app/robots/[id]/page.tsx`, replace both occurrences of `https://nomi-api.zhuchao.life/api/tts/speak` with `/api/tts/speak`. There are two occurrences:

Line 170 — change:
```typescript
if (el) { el.src = `https://nomi-api.zhuchao.life/api/tts/speak?text=${encodeURIComponent(`你好，我是${robot.name}。这是我的新声音。`)}&robot_id=${robot.id}&_t=${Date.now()}`; el.play().catch(() => {}); }
```
to:
```typescript
if (el) { el.src = `/api/tts/speak?text=${encodeURIComponent(`你好，我是${robot.name}。这是我的新声音。`)}&robot_id=${robot.id}&_t=${Date.now()}`; el.play().catch(() => {}); }
```

Line 177 — change:
```typescript
if (el) { el.src = `https://nomi-api.zhuchao.life/api/tts/speak?text=${encodeURIComponent(`你好，我是${robot.name}。${robot.core_desire}。这就是我的声音。`)}&robot_id=${robot.id}`; el.play().catch(() => {}); }
```
to:
```typescript
if (el) { el.src = `/api/tts/speak?text=${encodeURIComponent(`你好，我是${robot.name}。${robot.core_desire}。这就是我的声音。`)}&robot_id=${robot.id}`; el.play().catch(() => {}); }
```

- [ ] **Step 3: Replace portrait section with rich display**

In the robot detail page, replace the portrait section (lines 236-247, the `{robot.portrait && (...)}` block) with:

```tsx
      {robot.portrait && (() => {
        const p = robot.portrait as Record<string, unknown>;
        const personality_now = p.personality_now as Record<string, unknown> | undefined;
        const inner_world = p.inner_world as Record<string, unknown> | undefined;
        return (<>
          {/* Self description */}
          <div className="glass shadow-nomi rounded-[20px] p-5">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-[10px] text-nomi-charcoal-muted">自述</span>
              <RegenButton label="重新生成" robotId={robot.id} module="portrait" onDone={reload} />
            </div>
            <p className="text-[13px] leading-[1.8] text-nomi-charcoal-soft">{p.current_self_description as string}</p>
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

          {/* How it speaks */}
          {personality_now?.how_it_speaks && (
            <div className="glass shadow-nomi rounded-[20px] p-5">
              <span className="text-[10px] text-nomi-charcoal-muted">说话方式</span>
              <p className="mt-1 text-[12px] text-nomi-charcoal-soft">{personality_now.how_it_speaks as string}</p>
              {personality_now.emotional_baseline && (
                <span className="mt-2 inline-block rounded-full bg-nomi-cream px-2.5 py-0.5 text-[10px] text-nomi-charcoal-muted">情绪基调：{personality_now.emotional_baseline as string}</span>
              )}
            </div>
          )}
        </>);
      })()}
```

- [ ] **Step 4: Add relationships section**

After the portrait section (before `</>)}` that closes the profile tab), add:

```tsx
      {/* Relationships */}
      {(robot.relationships_snapshot as { name: string; role: string; status: string; memories: string[] }[] | null)?.length ? (
        <div className="glass shadow-nomi rounded-[20px] p-5">
          <span className="text-[10px] text-nomi-charcoal-muted">关系</span>
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
        </div>
      ) : null}
```

- [ ] **Step 5: Build and verify**

```bash
cd /Users/chao/projects/nomi/frontend && npx next build
```

Expected: Build succeeds.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/types.ts 'frontend/src/app/robots/[id]/page.tsx'
git commit -m "feat: rich portrait display, relationships section, fix TTS URLs"
```

---

### Task 4: Deploy and test

- [ ] **Step 1: Restart backend**

```bash
pm2 restart nomi-backend
```

- [ ] **Step 2: Restart frontend**

```bash
pm2 restart nomi-frontend
```

- [ ] **Step 3: Test TTS**

Open `https://nomi.zhuchao.life/robots/<ID>` and click the voice button. Should play audio without errors.

- [ ] **Step 4: Test with a new robot**

Create a new robot to verify:
- Memory diversity (different types of events, not just repetitive scenes)
- Structured relationships in ongoing_state
- relationships_snapshot saved to DB
- Portrait sections display correctly
- Relationships section shows with expandable memories

```bash
curl -s -X POST https://nomi-api.zhuchao.life/api/robots/from-image -F "text_hint=一只旧的毛绒玩偶熊，被很多小孩抱过，耳朵有缝补痕迹"
```

- [ ] **Step 5: Commit any fixes**

```bash
git add -u
git commit -m "fix: adjustments from end-to-end testing"
```
