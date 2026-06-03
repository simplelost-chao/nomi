"""做梦周期：定期整理某个机器人的记忆（去重 → 语义整合 → 安全遗忘）。

plan_dedup / plan_related_clusters 是纯函数（无 IO，可单测）；
run_sleep_cycle 负责 DB 落地。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ActivityLog, Memory, Robot
from app.services.memory_iteration import ForgetCandidate, cluster_by_similarity, should_forget

_CONSOLIDATE_PROMPT = """你是记忆整理助手。把下面这一组相关的零碎记忆，概括成一条更高层的「印象/认识」（第三人称，1-2句，抓住共性，不要罗列）。

记忆组：
{cluster_text}

只输出概括后的那一句话。"""


def plan_dedup(memories: list, threshold: float = 0.92) -> list[tuple]:
    """返回 [(loser_id, winner_id)]：每个近重复簇里，弱者并入最强者。"""
    merges: list[tuple] = []
    for cluster in cluster_by_similarity(memories, threshold):
        if len(cluster) < 2:
            continue
        winner = max(cluster, key=lambda m: m.importance_score or m.base_importance or 0.0)
        for m in cluster:
            if m.id != winner.id:
                merges.append((m.id, winner.id))
    return merges


def plan_related_clusters(memories: list, threshold: float = 0.75, min_size: int = 3) -> list[list]:
    """Clusters of RELATED (not just duplicate) memories worth consolidating into one semantic memory."""
    return [c for c in cluster_by_similarity(memories, threshold) if len(c) >= min_size]


async def run_sleep_cycle(session: AsyncSession, llm, robot: Robot,
                          dedup_threshold: float = 0.92) -> dict:
    """对单个机器人跑一轮做梦。返回统计 dict。

    Stages (in order):
      1. Dedup  — near-duplicate episodics fold into strongest copy.
      2. Semantic consolidation — related-but-distinct episodics are summarised
         into a new semantic memory by the LLM; cluster members get
         consolidated_into set so the forget loop below archives them this cycle.
      3. Safe-forget — archive anything whose consolidated_into is set, or that
         is old/unused/unimportant.
    """
    now = datetime.utcnow()
    result = await session.execute(
        select(Memory)
        .where(Memory.owner_id == robot.id)
        .where(Memory.archived.is_(False))
    )
    mems = [m for m in result.scalars().all() if m.embedding is not None]

    # ── Stage 1: dedup ───────────────────────────────────────────────────────
    by_id = {m.id: m for m in mems}
    merges = plan_dedup(mems, dedup_threshold)
    for loser_id, winner_id in merges:
        loser, winner = by_id.get(loser_id), by_id.get(winner_id)
        if loser is None or winner is None:
            continue
        loser.consolidated_into = winner.id
        winner.importance_score = min(1.0, (winner.importance_score or 0.0)
                                      + 0.5 * (loser.importance_score or 0.0))

    # ── Stage 2: semantic consolidation ──────────────────────────────────────
    # Runs BEFORE the forget loop so cluster members are archived in this cycle.
    promoted = 0
    if llm is not None:
        episodics = [m for m in mems if (m.memory_layer or "episodic") == "episodic"
                     and m.consolidated_into is None]
        from app.services.memory import MemoryService
        svc = MemoryService(session=session, llm=llm)
        for cluster in plan_related_clusters(episodics, threshold=0.75, min_size=3):
            cluster_text = "\n".join(f"- {m.summary or m.content or ''}" for m in cluster)
            try:
                summary = (await llm.generate(
                    [{"role": "user", "content": _CONSOLIDATE_PROMPT.format(cluster_text=cluster_text)}]
                )).strip()
            except Exception:
                continue
            if not summary:
                continue
            avg_imp = sum((m.importance_score or 0.0) for m in cluster) / len(cluster)
            sem = await svc.write_memory(
                user_id=robot.user_id, owner_type="robot", owner_id=robot.id,
                memory_type="semantic", content=summary, importance_score=avg_imp,
                summary=summary,
            )
            sem.memory_layer = "semantic"
            sem.linked_memory_ids = [m.id for m in cluster]
            for m in cluster:
                m.consolidated_into = sem.id
            promoted += 1
        await session.commit()

    # ── Stage 3: safe-forget ─────────────────────────────────────────────────
    forgotten = 0
    for m in mems:
        cand = ForgetCandidate(
            consolidated_into=m.consolidated_into,
            utility_score=m.utility_score or 0.0,
            importance_score=m.importance_score or 0.0,
            created_at=m.created_at or now,
            archived=m.archived,
        )
        if should_forget(cand, now):
            m.archived = True
            forgotten += 1

    stats = {"merged": len(merges), "forgotten": forgotten, "scanned": len(mems),
             "promoted": promoted}
    session.add(ActivityLog(robot_id=robot.id, event_type="sleep",
                            content="memory metabolism", detail=stats))
    await session.commit()
    return stats
