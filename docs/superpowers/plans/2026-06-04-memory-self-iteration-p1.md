# 记忆自迭代 P1 实现计划（基础闭环）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给记忆系统加上「反馈信号 + 混合检索 + 做梦周期（去重/整合/安全遗忘）」，实现「记忆越用越精 + 检索越用越准」。

**Architecture:** 把可测试的纯逻辑放进新模块 `app/services/memory_iteration.py`（EMA、混合打分、时近衰减、安全遗忘判定、相似聚类），DB 层薄封装。检索改为「向量取候选 → 混合分重排」。新增 `app/services/sleep_cycle.py` 做梦周期，复用心跳 loop 触发。`Memory` 表加 5 个字段。

**Tech Stack:** FastAPI · SQLAlchemy 2.0 async · Alembic · pytest · pgvector / SQLite。

**对应 spec:** `docs/superpowers/specs/2026-06-04-memory-self-iteration-design.md`（P1 部分）。

**说明:** spec 中「启用 reinterpretation 进人格」经核查 `check_evolution`（memory_evolution.py:46）已实现，故本计划不含该项。`memory_layer` 字段属 P2，本计划不加。

---

### Task 1: Memory 表新增自迭代字段 + 迁移

**Files:**
- Modify: `backend/app/db/models.py`（`Memory` 类，在 `memory_source` 字段后追加）
- Create: `backend/alembic/versions/a1b2c3d4e5f6_add_memory_iteration_fields.py`
- Test: `backend/tests/test_models_sqlite.py`（追加一个用例）

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_models_sqlite.py` 末尾）

```python
def test_memory_iteration_fields_exist(sqlite_engine):
    import uuid
    from sqlalchemy.orm import Session
    from app.db.models import User, Memory

    with Session(sqlite_engine) as session:
        user = User(id=uuid.uuid4(), name="t")
        session.add(user)
        session.flush()
        m = Memory(id=uuid.uuid4(), user_id=user.id, content="hi")
        session.add(m)
        session.commit()
        fetched = session.get(Memory, m.id)
        assert fetched.retrieved_count == 0
        assert fetched.useful_count == 0
        assert fetched.utility_score == 0.0
        assert fetched.consolidated_into is None
        assert fetched.archived is False
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd backend && NOMI_DATABASE_URL=sqlite+aiosqlite:///test.db pytest tests/test_models_sqlite.py::test_memory_iteration_fields_exist -v`
Expected: FAIL（`AttributeError: 'Memory' object has no attribute 'retrieved_count'` 或字段不存在）

- [ ] **Step 3: 给 Memory 模型加字段**（`app/db/models.py`，在 `memory_source` 行后插入）

```python
    memory_source: Mapped[str | None] = mapped_column(Text, default="conversation")
    # --- Self-iteration (P1) ---
    retrieved_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    useful_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    utility_score: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    consolidated_into: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false())
```

注意：文件顶部需有 `Boolean` 导入（已用于其他模型则无需重复）。`sa_false()` 用 `from sqlalchemy import false as sa_false`；若文件已 `import sqlalchemy as sa`，可改用 `server_default=sa.false()`。先确认现有导入风格再二选一。

- [ ] **Step 4: 写 alembic 迁移**（`alembic/versions/a1b2c3d4e5f6_add_memory_iteration_fields.py`）

```python
"""add memory self-iteration fields

Revision ID: a1b2c3d4e5f6
Revises: 9346fcfb1039
Create Date: 2026-06-04 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '9346fcfb1039'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('memories', sa.Column('retrieved_count', sa.Integer(), server_default='0', nullable=False))
    op.add_column('memories', sa.Column('useful_count', sa.Integer(), server_default='0', nullable=False))
    op.add_column('memories', sa.Column('utility_score', sa.Float(), server_default='0', nullable=False))
    op.add_column('memories', sa.Column('consolidated_into', sa.Uuid(), nullable=True))
    op.add_column('memories', sa.Column('archived', sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    for col in ('archived', 'consolidated_into', 'utility_score', 'useful_count', 'retrieved_count'):
        op.drop_column('memories', col)
```

> 确认 `down_revision` 是当前最新 revision（`alembic heads` 查；本计划写作时为 `9346fcfb1039`）。

- [ ] **Step 5: 运行测试，确认通过**

Run: `cd backend && NOMI_DATABASE_URL=sqlite+aiosqlite:///test.db pytest tests/test_models_sqlite.py::test_memory_iteration_fields_exist -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add backend/app/db/models.py backend/alembic/versions/a1b2c3d4e5f6_add_memory_iteration_fields.py backend/tests/test_models_sqlite.py
git commit -m "feat(memory): add self-iteration fields to Memory"
```

---

### Task 2: 纯函数 `update_utility`（有用率 EMA）

**Files:**
- Create: `backend/app/services/memory_iteration.py`
- Test: `backend/tests/test_memory_iteration.py`

- [ ] **Step 1: 写失败测试**（新建 `tests/test_memory_iteration.py`）

```python
import pytest


def test_update_utility_used_increases():
    from app.services.memory_iteration import update_utility
    assert update_utility(0.0, True, alpha=0.3) == pytest.approx(0.3)


def test_update_utility_unused_decreases():
    from app.services.memory_iteration import update_utility
    assert update_utility(1.0, False, alpha=0.3) == pytest.approx(0.7)


def test_update_utility_converges_toward_one():
    from app.services.memory_iteration import update_utility
    u = 0.0
    for _ in range(50):
        u = update_utility(u, True, alpha=0.3)
    assert u > 0.99
```

- [ ] **Step 2: 运行，确认失败**

Run: `cd backend && pytest tests/test_memory_iteration.py -v`
Expected: FAIL（`ModuleNotFoundError: app.services.memory_iteration`）

- [ ] **Step 3: 实现**（新建 `app/services/memory_iteration.py`）

```python
"""Pure, testable helpers for the self-iterating memory system (P1).

These functions contain no DB/IO so they can be unit-tested directly,
mirroring the style of app/services/memory.cosine_similarity.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.services.memory import cosine_similarity


def update_utility(old_utility: float, used: bool, alpha: float = 0.3) -> float:
    """Exponential moving average of a memory's usefulness.

    used=True moves the score toward 1.0, used=False toward 0.0.
    """
    target = 1.0 if used else 0.0
    return (1.0 - alpha) * old_utility + alpha * target
```

- [ ] **Step 4: 运行，确认通过**

Run: `cd backend && pytest tests/test_memory_iteration.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/memory_iteration.py backend/tests/test_memory_iteration.py
git commit -m "feat(memory): add update_utility EMA helper"
```

---

### Task 3: 纯函数 `recency_decay`

**Files:**
- Modify: `backend/app/services/memory_iteration.py`
- Test: `backend/tests/test_memory_iteration.py`

- [ ] **Step 1: 写失败测试**（追加）

```python
def test_recency_decay_now_is_one():
    from app.services.memory_iteration import recency_decay
    assert recency_decay(0.0) == pytest.approx(1.0)


def test_recency_decay_half_life():
    from app.services.memory_iteration import recency_decay
    assert recency_decay(168.0, half_life_hours=168.0) == pytest.approx(0.5)
```

- [ ] **Step 2: 运行，确认失败** — Run: `cd backend && pytest tests/test_memory_iteration.py::test_recency_decay_half_life -v` → FAIL（未定义）

- [ ] **Step 3: 实现**（追加到 `memory_iteration.py`）

```python
def recency_decay(hours_since: float, half_life_hours: float = 168.0) -> float:
    """1.0 at 0h, 0.5 at half_life (default 7 days), asymptotes to 0."""
    if hours_since <= 0:
        return 1.0
    return 0.5 ** (hours_since / half_life_hours)
```

- [ ] **Step 4: 运行，确认通过** — Run: `cd backend && pytest tests/test_memory_iteration.py -v` → PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/memory_iteration.py backend/tests/test_memory_iteration.py
git commit -m "feat(memory): add recency_decay helper"
```

---

### Task 4: 纯函数 `hybrid_score`

**Files:**
- Modify: `backend/app/services/memory_iteration.py`
- Test: `backend/tests/test_memory_iteration.py`

- [ ] **Step 1: 写失败测试**（追加）

```python
def test_hybrid_score_weights_sum_applied():
    from app.services.memory_iteration import hybrid_score, HYBRID_WEIGHTS
    # all signals = 1.0 → score = sum of weights
    s = hybrid_score(1.0, 1.0, 1.0, 1.0)
    assert s == pytest.approx(sum(HYBRID_WEIGHTS))


def test_hybrid_score_prefers_higher_utility():
    from app.services.memory_iteration import hybrid_score
    low = hybrid_score(0.8, 0.5, 0.0, 0.5)
    high = hybrid_score(0.8, 0.5, 1.0, 0.5)
    assert high > low
```

- [ ] **Step 2: 运行，确认失败** → FAIL（未定义）

- [ ] **Step 3: 实现**（追加）

```python
# weights: (cosine, importance, utility, recency)
HYBRID_WEIGHTS: tuple[float, float, float, float] = (0.5, 0.2, 0.2, 0.1)


def hybrid_score(
    cosine_sim: float,
    importance: float,
    utility: float,
    recency: float,
    weights: tuple[float, float, float, float] = HYBRID_WEIGHTS,
) -> float:
    """Weighted blend of semantic similarity + pragmatic signals."""
    w1, w2, w3, w4 = weights
    return w1 * cosine_sim + w2 * importance + w3 * utility + w4 * recency
```

- [ ] **Step 4: 运行，确认通过** → PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/memory_iteration.py backend/tests/test_memory_iteration.py
git commit -m "feat(memory): add hybrid_score ranking helper"
```

---

### Task 5: 纯函数 `should_forget`（安全遗忘判定）

**Files:**
- Modify: `backend/app/services/memory_iteration.py`
- Test: `backend/tests/test_memory_iteration.py`

- [ ] **Step 1: 写失败测试**（追加）

```python
def test_should_forget_consolidated_is_true():
    import uuid
    from datetime import datetime
    from app.services.memory_iteration import should_forget, ForgetCandidate
    m = ForgetCandidate(consolidated_into=uuid.uuid4(), utility_score=0.9,
                        importance_score=0.9, created_at=datetime(2026, 1, 1), archived=False)
    assert should_forget(m, datetime(2026, 6, 4)) is True


def test_should_forget_high_value_kept():
    from datetime import datetime
    from app.services.memory_iteration import should_forget, ForgetCandidate
    m = ForgetCandidate(consolidated_into=None, utility_score=0.8,
                        importance_score=0.8, created_at=datetime(2026, 1, 1), archived=False)
    assert should_forget(m, datetime(2026, 6, 4)) is False


def test_should_forget_low_value_old_is_true():
    from datetime import datetime
    from app.services.memory_iteration import should_forget, ForgetCandidate
    m = ForgetCandidate(consolidated_into=None, utility_score=0.0,
                        importance_score=0.1, created_at=datetime(2026, 1, 1), archived=False)
    assert should_forget(m, datetime(2026, 6, 4)) is True


def test_should_forget_already_archived_is_false():
    from datetime import datetime
    from app.services.memory_iteration import should_forget, ForgetCandidate
    m = ForgetCandidate(consolidated_into=None, utility_score=0.0,
                        importance_score=0.0, created_at=datetime(2026, 1, 1), archived=True)
    assert should_forget(m, datetime(2026, 6, 4)) is False
```

- [ ] **Step 2: 运行，确认失败** → FAIL

- [ ] **Step 3: 实现**（追加）

```python
@dataclass
class ForgetCandidate:
    consolidated_into: object  # uuid.UUID | None
    utility_score: float
    importance_score: float
    created_at: datetime
    archived: bool


def should_forget(
    m: ForgetCandidate,
    now: datetime,
    *,
    age_days: float = 30.0,
    util_floor: float = 0.1,
    importance_floor: float = 0.2,
) -> bool:
    """Safe-forget predicate. NEVER forgets recent/useful/important memories.

    Archive only when:
      - already absorbed by a consolidation (consolidated_into set), OR
      - low utility AND low importance AND old (all three).
    """
    if m.archived:
        return False
    if m.consolidated_into is not None:
        return True
    age = (now - m.created_at).total_seconds() / 86400.0
    return (
        m.utility_score < util_floor
        and m.importance_score < importance_floor
        and age > age_days
    )
```

- [ ] **Step 4: 运行，确认通过** → PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/memory_iteration.py backend/tests/test_memory_iteration.py
git commit -m "feat(memory): add safe should_forget predicate"
```

---

### Task 6: 纯函数 `cluster_by_similarity`（去重/整合聚类）

**Files:**
- Modify: `backend/app/services/memory_iteration.py`
- Test: `backend/tests/test_memory_iteration.py`

- [ ] **Step 1: 写失败测试**（追加）

```python
class _Item:
    def __init__(self, name, embedding):
        self.name = name
        self.embedding = embedding


def test_cluster_groups_near_duplicates():
    from app.services.memory_iteration import cluster_by_similarity
    items = [
        _Item("a", [1.0, 0.0, 0.0]),
        _Item("a2", [0.99, 0.01, 0.0]),   # near-duplicate of a
        _Item("b", [0.0, 1.0, 0.0]),       # different
    ]
    clusters = cluster_by_similarity(items, threshold=0.95)
    sizes = sorted(len(c) for c in clusters)
    assert sizes == [1, 2]


def test_cluster_singletons_when_all_different():
    from app.services.memory_iteration import cluster_by_similarity
    items = [_Item("a", [1.0, 0.0]), _Item("b", [0.0, 1.0])]
    clusters = cluster_by_similarity(items, threshold=0.95)
    assert len(clusters) == 2
```

- [ ] **Step 2: 运行，确认失败** → FAIL

- [ ] **Step 3: 实现**（追加）

```python
def cluster_by_similarity(items: list, threshold: float = 0.92) -> list[list]:
    """Greedy single-pass clustering by cosine of each item's `.embedding`.

    Each item is compared to existing cluster representatives (first member);
    joins the first cluster above `threshold`, else starts a new cluster.
    Items with no embedding become singletons. Returns clusters (incl. singletons).
    """
    clusters: list[list] = []
    for item in items:
        emb = getattr(item, "embedding", None)
        placed = False
        if emb is not None:
            for cluster in clusters:
                rep_emb = getattr(cluster[0], "embedding", None)
                if rep_emb is not None and cosine_similarity(rep_emb, emb) >= threshold:
                    cluster.append(item)
                    placed = True
                    break
        if not placed:
            clusters.append([item])
    return clusters
```

- [ ] **Step 4: 运行，确认通过** → PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/memory_iteration.py backend/tests/test_memory_iteration.py
git commit -m "feat(memory): add cluster_by_similarity helper"
```

---

### Task 7: 检索改为混合排序（候选 → 重排）

**Files:**
- Modify: `backend/app/services/memory.py`（`search_memories` 与 `_search_memories_sqlite`）
- Test: `backend/tests/test_memory_iteration.py`（重排函数纯逻辑测试）

新增一个纯重排函数，DB 两路都用它，便于单测。

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_memory_iteration.py`）

```python
class _Mem:
    def __init__(self, name, embedding, importance, utility, last_activated):
        self.name = name
        self.embedding = embedding
        self.importance_score = importance
        self.utility_score = utility
        self.last_activated = last_activated
        self.created_at = last_activated


def test_rerank_prefers_useful_over_pure_cosine():
    from datetime import datetime
    from app.services.memory_iteration import rerank_candidates
    now = datetime(2026, 6, 4)
    q = [1.0, 0.0]
    # m_close: slightly closer cosine but never useful
    m_close = _Mem("close", [1.0, 0.0], importance=0.3, utility=0.0, last_activated=now)
    # m_useful: a bit farther but high importance+utility
    m_useful = _Mem("useful", [0.9, 0.1], importance=0.9, utility=0.9, last_activated=now)
    ranked = rerank_candidates([m_close, m_useful], q, now, limit=1)
    assert ranked[0].name == "useful"


def test_rerank_respects_limit():
    from datetime import datetime
    from app.services.memory_iteration import rerank_candidates
    now = datetime(2026, 6, 4)
    mems = [_Mem(str(i), [1.0, 0.0], 0.5, 0.5, now) for i in range(5)]
    assert len(rerank_candidates(mems, [1.0, 0.0], now, limit=3)) == 3
```

- [ ] **Step 2: 运行，确认失败** → FAIL（`rerank_candidates` 未定义）

- [ ] **Step 3: 实现 `rerank_candidates`**（追加到 `memory_iteration.py`）

```python
def rerank_candidates(candidates: list, query_embedding: list[float], now: datetime,
                      limit: int, weights=HYBRID_WEIGHTS) -> list:
    """Re-rank already-fetched memory candidates by hybrid_score, return top `limit`.

    Each candidate needs: .embedding, .importance_score, .utility_score,
    .last_activated (or .created_at).
    """
    scored = []
    for m in candidates:
        if m.embedding is None:
            continue
        cos = cosine_similarity(query_embedding, m.embedding)
        last = getattr(m, "last_activated", None) or getattr(m, "created_at", None) or now
        hours = max(0.0, (now - last).total_seconds() / 3600.0)
        score = hybrid_score(
            cos,
            m.importance_score or 0.0,
            getattr(m, "utility_score", 0.0) or 0.0,
            recency_decay(hours),
            weights,
        )
        scored.append((m, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [m for m, _ in scored[:limit]]
```

- [ ] **Step 4: 运行，确认通过** → PASS

- [ ] **Step 5: 接到 `search_memories`**（`app/services/memory.py`）。把 pg 路径改为「取候选 K' 再重排」：

```python
    async def search_memories(self, query, user_id, owner_id=None, limit=3):
        if settings.is_sqlite:
            return await self._search_memories_sqlite(query, user_id, owner_id, limit)

        from datetime import datetime as _dt
        from app.services.memory_iteration import rerank_candidates

        query_embedding = await self.llm.embed(query)
        candidate_k = max(limit * 5, 20)
        stmt = (
            select(Memory)
            .where(Memory.user_id == user_id)
            .where(Memory.embedding.isnot(None))
            .where(Memory.archived.is_(False))
        )
        if owner_id:
            stmt = stmt.where(Memory.owner_id == owner_id)
        stmt = stmt.order_by(Memory.embedding.cosine_distance(query_embedding)).limit(candidate_k)

        result = await self.session.execute(stmt)
        candidates = list(result.scalars().all())
        memories = rerank_candidates(candidates, query_embedding, _dt.utcnow(), limit)

        for memory in memories:
            memory.last_accessed_at = _dt.utcnow()
        await self.session.commit()
        return memories
```

- [ ] **Step 6: 同样改 `_search_memories_sqlite`**：把现有「按 cosine 排序取 limit」替换为：

```python
        result = await self.session.execute(stmt)  # stmt 同前，追加 .where(Memory.archived.is_(False))
        all_memories = [m for m in result.scalars().all() if m.embedding is not None]
        from app.services.memory_iteration import rerank_candidates
        memories = rerank_candidates(all_memories, query_embedding, datetime.utcnow(), limit)
        for memory in memories:
            memory.last_accessed_at = datetime.utcnow()
        await self.session.commit()
        return memories
```

注意：两路 `stmt` 都加 `.where(Memory.archived.is_(False))` 以排除已遗忘记忆。

- [ ] **Step 7: 跑现有记忆测试，确认未回归**

Run: `cd backend && pytest tests/test_memory.py tests/test_memory_sqlite.py tests/test_memory_iteration.py -v`
Expected: PASS（如个别旧用例假设纯 cosine 顺序，按混合排序语义更新断言）

- [ ] **Step 8: 提交**

```bash
git add backend/app/services/memory.py backend/app/services/memory_iteration.py backend/tests/test_memory_iteration.py
git commit -m "feat(memory): hybrid-ranked retrieval (candidate fetch + rerank)"
```

---

### Task 8: 反馈记账函数 `record_retrieval` / `record_usefulness`

**Files:**
- Modify: `backend/app/services/memory_evolution.py`（追加两个函数）
- Test: `backend/tests/test_memory_evolution_feedback.py`（新建，SQLite 集成）

- [ ] **Step 1: 写失败测试**（新建 `tests/test_memory_evolution_feedback.py`）

```python
import os
import uuid
import pytest

pytestmark = pytest.mark.skipif(
    "sqlite" not in os.environ.get("NOMI_DATABASE_URL", ""),
    reason="requires NOMI_DATABASE_URL=sqlite+aiosqlite:///test.db",
)


@pytest.mark.asyncio
async def test_record_usefulness_updates_scores():
    from app.db.engine import async_session
    from app.db.models import User, Memory
    from app.services.memory_evolution import record_retrieval, record_usefulness

    uid = uuid.uuid4()
    m1, m2 = uuid.uuid4(), uuid.uuid4()
    async with async_session() as s:
        s.add(User(id=uid, name="t"))
        s.add(Memory(id=m1, user_id=uid, content="a"))
        s.add(Memory(id=m2, user_id=uid, content="b"))
        await s.commit()

    async with async_session() as s:
        await record_retrieval(s, [m1, m2])
        await record_usefulness(s, retrieved_ids=[m1, m2], used_ids=[m1])

    async with async_session() as s:
        a = await s.get(Memory, m1)
        b = await s.get(Memory, m2)
        assert a.retrieved_count == 1 and a.useful_count == 1
        assert a.utility_score > b.utility_score   # m1 used, m2 not
        assert b.useful_count == 0
```

> 运行此类异步 DB 测试需 `pytest-asyncio` 与 `NOMI_DATABASE_URL=sqlite+aiosqlite:///test.db`，并已 `alembic upgrade head` 或 `Base.metadata.create_all`。若仓库暂无 async DB 测试夹具，本任务可先只做实现 + 用一次性脚本验证，测试留作 follow-up（在提交信息注明）。

- [ ] **Step 2: 运行，确认失败** → FAIL（函数未定义）

- [ ] **Step 3: 实现**（追加到 `memory_evolution.py`，复用已 import 的 `select`/`Memory`）

```python
from app.services.memory_iteration import update_utility  # 顶部 import 区


async def record_retrieval(session: AsyncSession, memory_ids: list[uuid.UUID]) -> None:
    """+1 retrieved_count for each memory that was pulled into a prompt."""
    if not memory_ids:
        return
    result = await session.execute(select(Memory).where(Memory.id.in_(memory_ids)))
    for m in result.scalars().all():
        m.retrieved_count = (m.retrieved_count or 0) + 1
    await session.commit()


async def record_usefulness(
    session: AsyncSession,
    retrieved_ids: list[uuid.UUID],
    used_ids: list[uuid.UUID],
    alpha: float = 0.3,
) -> None:
    """Update utility EMA for retrieved memories based on whether the LLM used them."""
    if not retrieved_ids:
        return
    used = set(used_ids or [])
    result = await session.execute(select(Memory).where(Memory.id.in_(retrieved_ids)))
    for m in result.scalars().all():
        was_used = m.id in used
        if was_used:
            m.useful_count = (m.useful_count or 0) + 1
        m.utility_score = update_utility(m.utility_score or 0.0, was_used, alpha)
    await session.commit()
```

- [ ] **Step 4: 运行，确认通过**（或按 Step 1 备注以脚本验证）

Run: `cd backend && NOMI_DATABASE_URL=sqlite+aiosqlite:///test.db pytest tests/test_memory_evolution_feedback.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/memory_evolution.py backend/tests/test_memory_evolution_feedback.py
git commit -m "feat(memory): record retrieval + usefulness feedback signal"
```

---

### Task 9: 接入反馈信号（agents/chat 自报 used_memory_ids + 修复心跳强化）

**Files:**
- Modify: `backend/app/api/agents.py`（chat 路径：编号注入记忆、解析 `used_memory_ids`、调 `record_*`）
- Modify: `backend/app/services/heartbeat.py`（检索后补 `activate_memories`）

- [ ] **Step 1: 心跳强化修复**（`heartbeat.py`，在语义检索得到 `memories` 后、约 line 356 附近）

```python
        # 修复：心跳召回的记忆也要被强化（与 agent/chat 对齐）
        if memories:
            from app.services.memory_evolution import activate_memories
            await activate_memories(session, [m.id for m in memories])
```

- [ ] **Step 2: agents/chat 编号注入 + 记账**（`agents.py`，记忆检索处约 line 372-401）

把注入的记忆带上稳定编号，并记录 `retrieved_ids`：

```python
    memories = await memory_service.search_memories(
        query=search_query, user_id=DEFAULT_USER_ID, owner_id=robot.id, limit=5,
    )
    retrieved_ids = [m.id for m in memories]
    from app.services.memory_evolution import record_retrieval
    await record_retrieval(bg_session, retrieved_ids)  # 用与下文一致的 session

    # 编号注入，便于 LLM 回引
    memory_lines = []
    id_by_tag = {}
    for i, m in enumerate(memories, 1):
        tag = f"M{i}"
        id_by_tag[tag] = m.id
        memory_lines.append(f"[{tag}] {m.summary or m.content or ''}")
    memory_block = "你的相关记忆（如果用到了某条，请在回复 JSON 的 used_memories 里写它的编号）：\n" + "\n".join(memory_lines)
```

- [ ] **Step 3: 让 LLM 回吐 used_memories，并解析记账**。在该端点构造回复的 system/JSON 约定里加入 `used_memories` 字段（字符串编号数组，如 `["M1"]`）。拿到模型输出后：

```python
    used_tags = parsed.get("used_memories", []) or []   # parsed = 模型 JSON 输出
    used_ids = [id_by_tag[t] for t in used_tags if t in id_by_tag]
    from app.services.memory_evolution import record_usefulness, activate_memories
    await record_usefulness(bg_session, retrieved_ids=retrieved_ids, used_ids=used_ids)
    if used_ids:
        await activate_memories(bg_session, used_ids)
```

> 若该端点回复非 JSON（纯文本），退化策略：把「被检索的」全部按 `used=False` 记一次（仍提供弱负反馈），并在注释标注 follow-up 改为结构化输出。保持改动局部、不破坏现有响应格式。

- [ ] **Step 4: 手动验证**：启动后端，走一次 `/api/agents/chat`，确认对应 memory 的 `retrieved_count` 增长、被引用的 `utility_score` 上升（查 DB 或加临时日志）。

Run: `cd backend && python -c "import app.api.agents"`（确保无导入/语法错误）
Expected: 无报错

- [ ] **Step 5: 提交**

```bash
git add backend/app/api/agents.py backend/app/services/heartbeat.py
git commit -m "feat(memory): wire used_memory feedback in agent chat; fix heartbeat reinforcement"
```

---

### Task 10: 做梦周期服务 `SleepCycle`（去重 → 整合 → 重打分&遗忘）

**Files:**
- Create: `backend/app/services/sleep_cycle.py`
- Test: `backend/tests/test_sleep_cycle.py`（纯编排逻辑用假对象测试；LLM 用桩）

- [ ] **Step 1: 写失败测试**（新建 `tests/test_sleep_cycle.py`，只测纯编排，不连 DB）

```python
import pytest
from datetime import datetime


def test_plan_dedup_merges_near_duplicates():
    from app.services.sleep_cycle import plan_dedup

    class M:
        def __init__(self, id, emb, imp):
            self.id, self.embedding, self.importance_score = id, emb, imp
            self.base_importance = imp
            self.consolidated_into = None
    a = M(1, [1.0, 0.0], 0.4)
    a2 = M(2, [0.99, 0.0], 0.3)   # dup of a
    b = M(3, [0.0, 1.0], 0.5)
    merges = plan_dedup([a, a2, b], threshold=0.95)
    # one merge group: weaker (a2) folds into stronger (a)
    assert merges == [(2, 1)]   # (loser_id, winner_id)


def test_plan_dedup_no_merge_when_distinct():
    from app.services.sleep_cycle import plan_dedup

    class M:
        def __init__(self, id, emb):
            self.id, self.embedding, self.importance_score = id, emb, 0.5
            self.base_importance = 0.5
    out = plan_dedup([M(1, [1.0, 0.0]), M(2, [0.0, 1.0])], threshold=0.95)
    assert out == []
```

- [ ] **Step 2: 运行，确认失败** → FAIL

- [ ] **Step 3: 实现纯编排 + 服务骨架**（新建 `sleep_cycle.py`）

```python
"""做梦周期：定期整理某个机器人的记忆（去重 → 整合 → 重打分&遗忘）。

纯编排函数（plan_*）无 IO、可单测；run_sleep_cycle 负责 DB/LLM 落地。
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ActivityLog, Memory, Robot
from app.services.memory_iteration import (
    ForgetCandidate,
    cluster_by_similarity,
    should_forget,
)


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
    """对单个机器人跑一轮做梦。返回统计 dict。"""
    now = datetime.utcnow()
    result = await session.execute(
        select(Memory)
        .where(Memory.owner_id == robot.id)
        .where(Memory.archived.is_(False))
    )
    mems = [m for m in result.scalars().all() if m.embedding is not None]

    # 1) 去重：弱者 consolidated_into = 强者，重要度累加
    by_id = {m.id: m for m in mems}
    merges = plan_dedup(mems, dedup_threshold)
    for loser_id, winner_id in merges:
        loser, winner = by_id.get(loser_id), by_id.get(winner_id)
        if loser is None or winner is None:
            continue
        loser.consolidated_into = winner.id
        winner.importance_score = min(1.0, (winner.importance_score or 0.0)
                                      + 0.5 * (loser.importance_score or 0.0))

    # 2) 重打分 & 安全遗忘
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
```

> 阶段 2「LLM 整合成更高层记忆」属本任务可选增强：当前实现以「去重并簇」为主、把弱者并入强者；用 LLM 概括整簇为新 `memory_type="consolidated"` 记忆留作 P1.5 增量（避免一次引入过多 LLM 调用）。如需现在就做，新增 `_consolidate_cluster(llm, cluster)` 调本地 LLM 概括，并把簇成员 `consolidated_into` 指向新记忆——逻辑与去重一致，仅 winner 换成新生成记忆。

- [ ] **Step 4: 运行，确认通过** → PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/sleep_cycle.py backend/tests/test_sleep_cycle.py
git commit -m "feat(memory): sleep cycle service (dedup + safe forget)"
```

---

### Task 11: 触发做梦周期（接入心跳 loop）

**Files:**
- Modify: `backend/app/services/heartbeat.py`（仿照现有 `_memory_decay_loop`，新增 `_sleep_cycle_loop`）

- [ ] **Step 1: 实现触发 loop**（`heartbeat.py`，仿 `_memory_decay_loop` 写法，约 line 971 附近）

```python
    async def _sleep_cycle_loop(self):
        """定期对每个机器人跑做梦周期。默认每 6 小时一轮。"""
        from app.services.sleep_cycle import run_sleep_cycle
        while self._alive:
            try:
                await asyncio.sleep(6 * 3600)
                async with async_session() as session:
                    robots = (await session.execute(select(Robot))).scalars().all()
                    for robot in robots:
                        try:
                            await run_sleep_cycle(session, self.llm, robot)
                        except Exception as e:
                            print(f"[sleep] {robot.name} failed: {e}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[sleep] loop error: {e}")
```

> 用与 `_memory_decay_loop` 相同的 import（`async_session`、`select`、`Robot`、`asyncio`）。简化起见先用固定 6 小时间隔；spec 中「空闲 30 分钟触发」可作 follow-up（需接入用户最近活跃时间）。

- [ ] **Step 2: 启动 loop**（在启动 `_memory_decay_loop` 的同一处，加一行）

```python
        asyncio.create_task(self._sleep_cycle_loop())
```

- [ ] **Step 3: 验证导入与启动无误**

Run: `cd backend && python -c "import app.services.heartbeat"`
Expected: 无报错

- [ ] **Step 4: 提交**

```bash
git add backend/app/services/heartbeat.py
git commit -m "feat(memory): schedule periodic sleep cycle in heartbeat loop"
```

---

## 验收（P1 整体）

- [ ] `cd backend && pytest tests/test_memory_iteration.py tests/test_models_sqlite.py -v` 全绿（纯函数 + 模型字段）。
- [ ] 走一次 agent 对话：被检索记忆 `retrieved_count` 增长；被引用的 `utility_score` 上升（验证「检索越用越准」的信号闭环）。
- [ ] 手动触发一次 `run_sleep_cycle`：近重复被并、低价值老记忆被 `archived`、`ActivityLog` 出现 `event_type="sleep"` 记录（验证「记忆越用越精」）。
- [ ] 检索结果排除 `archived=True` 记忆。

## 交付边界与 follow-up（不在 P1）

- LLM 整合成 `consolidated` 高层记忆（Task 10 Step 3 备注）→ P1.5。
- 「空闲检测」触发（当前用固定间隔）→ follow-up。
- 洞见提纯 / 记忆金字塔 `memory_layer` / 人格漂移检测 → P2。
- 元调参 → P3。
