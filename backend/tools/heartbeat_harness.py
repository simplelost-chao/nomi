"""测试平台:加速心跳 + 多轮对话,观察一个角色自主产生的记忆 / 知识 / 技能。

通过本地后端(http://localhost:8100)的真实接口驱动:
  - 对话:POST /api/agents/chat
  - 心跳动作:POST /api/heartbeat/trigger/{robot_id}/{action}  (thought|search|skill|reflect)
然后查库做前后快照对比,打印一份"涌现报告"。

用法:
  cd backend && .venv/bin/python3.12 tools/heartbeat_harness.py [角色名=Anya] [对话轮数=4] [心跳拍数=8]
"""
import asyncio
import os
import sys

# 让 app.* 可导入(脚本在 backend/tools/ 下)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("NOMI_DATABASE_URL", "postgresql+asyncpg://nomi:nomi@localhost:5432/nomi?ssl=disable")

import httpx
from sqlalchemy import func, select

from app.db.engine import async_session
from app.db.models import ActivityLog, Memory, Robot, RobotSkill

BASE = "http://localhost:8100"

# 测试用对话(可自行替换)
CHAT_MESSAGES = [
    "アーニャ、今日は何して遊んだの？",
    "你今天有没有学到什么新东西呀？",
    "如果可以许一个愿望，你最想要什么？",
    "你最喜欢谁？为什么呀？",
    "有没有什么事情让你觉得有点害怕？",
    "给我讲一个你觉得最开心的事吧。",
]
# 心跳动作循环(search 较慢,故穿插)
BEAT_CYCLE = ["thought", "search", "thought", "reflect", "skill", "thought", "search", "reflect"]


def _post(path: str, json_body: dict | None = None, timeout: float = 120.0) -> dict:
    """同步 httpx 调本地后端(localhost 可靠)。"""
    try:
        r = httpx.post(f"{BASE}{path}", json=json_body or {}, timeout=timeout)
        if r.status_code != 200:
            return {"_http": r.status_code, "_body": r.text[:200]}
        return r.json()
    except Exception as e:
        return {"_error": f"{type(e).__name__}: {str(e)[:150]}"}


async def snapshot(rid) -> dict:
    """角色当前状态计数 + 各集合的 id,用于前后 diff。"""
    async with async_session() as s:
        mem_ids = set((await s.execute(select(Memory.id).where(Memory.owner_id == rid))).scalars().all())
        skills = (await s.execute(select(RobotSkill).where(RobotSkill.robot_id == rid))).scalars().all()
        act = (await s.execute(select(ActivityLog.id).where(ActivityLog.robot_id == rid))).scalars().all()
        return {
            "mem_ids": mem_ids,
            "skills": {sk.id: sk for sk in skills},
            "act_ids": set(act),
        }


async def new_memories(rid, before_ids: set) -> list[Memory]:
    async with async_session() as s:
        rows = (await s.execute(
            select(Memory).where(Memory.owner_id == rid).where(Memory.id.notin_(before_ids or {None}))
            .order_by(Memory.created_at)
        )).scalars().all()
        return rows


async def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "Anya"
    n_chats = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    n_beats = int(sys.argv[3]) if len(sys.argv) > 3 else 8

    async with async_session() as s:
        robot = (await s.execute(select(Robot).where(Robot.name == name))).scalars().first()
    if not robot:
        print(f"角色 {name} 不存在"); return
    rid = robot.id
    print(f"=== 测试平台:【{name}】 对话{n_chats}轮 + 心跳{n_beats}拍(加速) ===\n")

    before = await snapshot(rid)
    print(f"基线:普通记忆 {len(before['mem_ids'])} | 技能 {len(before['skills'])} | 活动日志 {len(before['act_ids'])}\n")

    # ── 阶段一:多轮对话 ──────────────────────────────────────────────
    print("── 阶段一:对话 ──")
    for i in range(n_chats):
        msg = CHAT_MESSAGES[i % len(CHAT_MESSAGES)]
        res = await asyncio.to_thread(_post, "/api/agents/chat", {"robot_id": str(rid), "message": msg}, 120.0)
        reply = res.get("reply") or res.get("_error") or res.get("_http") or "(无回复)"
        print(f"  你: {msg}")
        print(f"  {name}: {str(reply)[:90]}")
        await asyncio.sleep(0.5)

    # ── 阶段二:加速心跳 ──────────────────────────────────────────────
    print("\n── 阶段二:加速心跳(间隔 1.5s) ──")
    for i in range(n_beats):
        action = BEAT_CYCLE[i % len(BEAT_CYCLE)]
        res = await asyncio.to_thread(_post, f"/api/heartbeat/trigger/{rid}/{action}", None, 150.0)
        if action == "search":
            q = res.get("query", "?")
            sm = (res.get("result") or {}).get("summary", "") if isinstance(res.get("result"), dict) else ""
            print(f"  [拍{i+1}·搜索] 「{q}」 → {sm[:70]}")
        elif action == "skill":
            sk = res.get("skill") or res.get("result")
            print(f"  [拍{i+1}·技能] {('✨ '+str(sk)) if sk else '本次未觉醒新技能'}")
        elif action == "reflect":
            rf = res.get("reflection") or res.get("result") or ""
            print(f"  [拍{i+1}·反思] {str(rf)[:70]}")
        else:  # thought
            th = res.get("result") or res.get("thought") or ""
            print(f"  [拍{i+1}·想法] {str(th)[:70]}")
        await asyncio.sleep(1.5)

    # ── 报告:涌现了什么 ─────────────────────────────────────────────
    after = await snapshot(rid)
    nm = await new_memories(rid, before["mem_ids"])
    knowledge = [m for m in nm if (m.content or "").startswith(("[学到的知识]", "[知识碎片]"))]
    convo = [m for m in nm if m not in knowledge]
    new_sk = [sk for sid, sk in after["skills"].items() if sid not in before["skills"]]

    print("\n" + "=" * 50)
    print("涌现报告")
    print("=" * 50)
    print(f"📝 新增记忆:{len(nm)} 条(对话/想法 {len(convo)},搜索知识 {len(knowledge)})")
    for m in convo[:6]:
        print(f"   · {(m.summary or m.content or '')[:64]}")
    if knowledge:
        print(f"\n🔍 自主学到的知识:{len(knowledge)} 条")
        for m in knowledge[:6]:
            print(f"   · {(m.content or '')[:64]}")
    print(f"\n✨ 新觉醒技能:{len(new_sk)} 个")
    for sk in new_sk:
        print(f"   · {sk.name}:{(sk.description or '')[:60]}")
    print(f"\n📊 活动日志新增:{len(after['act_ids'] - before['act_ids'])} 条")


if __name__ == "__main__":
    asyncio.run(main())
