"""做梦周期：定期整理某个机器人的记忆（去重 → 重打分&安全遗忘）。

plan_dedup 是纯函数（无 IO，可单测）；run_sleep_cycle 负责 DB 落地。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ActivityLog, Memory, Robot
from app.services.memory_iteration import ForgetCandidate, cluster_by_similarity, should_forget


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


async def run_sleep_cycle(session: AsyncSession, llm, robot: Robot,
                          dedup_threshold: float = 0.92) -> dict:
    """对单个机器人跑一轮做梦。返回统计 dict。llm 预留给后续整合阶段，当前未用。"""
    now = datetime.utcnow()
    result = await session.execute(
        select(Memory)
        .where(Memory.owner_id == robot.id)
        .where(Memory.archived.is_(False))
    )
    mems = [m for m in result.scalars().all() if m.embedding is not None]

    by_id = {m.id: m for m in mems}
    merges = plan_dedup(mems, dedup_threshold)
    for loser_id, winner_id in merges:
        loser, winner = by_id.get(loser_id), by_id.get(winner_id)
        if loser is None or winner is None:
            continue
        loser.consolidated_into = winner.id
        winner.importance_score = min(1.0, (winner.importance_score or 0.0)
                                      + 0.5 * (loser.importance_score or 0.0))

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

    stats = {"merged": len(merges), "forgotten": forgotten, "scanned": len(mems)}
    session.add(ActivityLog(robot_id=robot.id, event_type="sleep",
                            content="memory metabolism", detail=stats))
    await session.commit()
    return stats
