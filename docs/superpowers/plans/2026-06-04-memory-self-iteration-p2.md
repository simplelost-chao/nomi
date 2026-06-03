# 记忆自迭代 P2 实现计划（记忆金字塔与人格连贯）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 把扁平记忆长成 episodic→semantic→principle 三层金字塔，做梦周期负责向上提炼，人格由 principle 驱动并加漂移检测，实现「人格越长越连贯」。

**Architecture:** 新增 `Memory.memory_layer`。纯逻辑（层预算分配、principle 排序加成、人格漂移距离与阻尼、principle 封顶淘汰）放进 `memory_iteration.py`（延续 P1 风格，可单测）。做梦周期 `sleep_cycle.py` 增「语义提炼」「洞见提纯」两阶；检索增分层版本；`memory_evolution.check_evolution` 改为 principle 驱动 + 漂移检测。

**Tech Stack:** FastAPI · SQLAlchemy async · Alembic · pytest（沿用 P1：sqlite-guard + `asyncio.run` 自包含异步测试；纯函数测试免 DB）。

**对应 spec:** `docs/superpowers/specs/2026-06-04-memory-self-iteration-p2-design.md`。

**前置:** P1 全部已实现（feature/memory-self-iteration 分支或已合并）。本计划在其基础上继续。

**默认参数(来自 spec §8):** 洞见频率=每 4 次做梦且有新 semantic；漂移阈值=0.35，阻尼 w=0.3，需 ≥2 principle 背书；principle 封顶=20；矛盾仅 confidence 差>0.3 时调和。

---

### Task 1: `memory_layer` 字段 + 迁移

**Files:** Modify `backend/app/db/models.py`（Memory）；Create `backend/alembic/versions/b2c3d4e5f6a7_add_memory_layer.py`；Test `backend/tests/test_models_sqlite.py`。

- [ ] **Step 1: 失败测试**（追加）

```python
def test_memory_layer_defaults_episodic(sqlite_engine):
    import uuid
    from sqlalchemy.orm import Session
    from app.db.models import User, Memory
    with Session(sqlite_engine) as s:
        u = User(id=uuid.uuid4(), name="t"); s.add(u); s.flush()
        m = Memory(id=uuid.uuid4(), user_id=u.id, content="x"); s.add(m); s.commit()
        assert s.get(Memory, m.id).memory_layer == "episodic"
```

- [ ] **Step 2: 跑，确认失败** — `cd backend && NOMI_DATABASE_URL=sqlite+aiosqlite:///test.db .venv/bin/python3.12 -m pytest tests/test_models_sqlite.py::test_memory_layer_defaults_episodic -v`

- [ ] **Step 3: 加字段**（Memory 类，紧接 P1 的 `archived` 字段后）

```python
    memory_layer: Mapped[str] = mapped_column(Text, default="episodic", server_default="episodic")
```

- [ ] **Step 4: 迁移**（down_revision 指向 P1 的 `a1b2c3d4e5f6`，先 `alembic heads` 确认）

```python
"""add memory_layer

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-04 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('memories', sa.Column('memory_layer', sa.Text(), server_default='episodic', nullable=False))

def downgrade() -> None:
    op.drop_column('memories', 'memory_layer')
```

- [ ] **Step 5: 跑通** — 同 Step 2 命令应 PASS；并跑全 `tests/test_models_sqlite.py`。
- [ ] **Step 6: 提交** — `feat(memory): add memory_layer field for pyramid`

---

### Task 2: 分层检索（层预算 + principle 加成）

**Files:** Modify `backend/app/services/memory_iteration.py`（加纯函数）；Modify `backend/app/services/memory.py`（加 `search_memories_layered`）；Test `backend/tests/test_memory_iteration.py`。

- [ ] **Step 1: 失败测试**（追加）

```python
def test_allocate_layer_budget_splits():
    from app.services.memory_iteration import allocate_layer_budget
    b = allocate_layer_budget(principles=2, semantic=2, episodic=2)
    assert b == {"principle": 2, "semantic": 2, "episodic": 2}


def test_principle_boost_lifts_score():
    from app.services.memory_iteration import apply_layer_boost
    assert apply_layer_boost(0.5, "principle") > apply_layer_boost(0.5, "episodic")
    assert apply_layer_boost(0.5, "episodic") == 0.5
```

- [ ] **Step 2: 跑，确认失败**
- [ ] **Step 3: 实现**（追加到 `memory_iteration.py`）

```python
LAYER_BOOST = {"principle": 0.25, "semantic": 0.1, "episodic": 0.0}


def allocate_layer_budget(principles: int = 2, semantic: int = 2, episodic: int = 2) -> dict:
    """Per-layer retrieval budget for prompt injection."""
    return {"principle": principles, "semantic": semantic, "episodic": episodic}


def apply_layer_boost(score: float, layer: str) -> float:
    """Add a constant retrieval boost by layer (principles are near-always-on)."""
    return score + LAYER_BOOST.get(layer or "episodic", 0.0)
```

- [ ] **Step 4: 跑通**
- [ ] **Step 5: 加 `search_memories_layered`**（`memory.py`，复用现有按 owner 的取候选 + `rerank_candidates`，逐层各取预算条，principle 层在排序分上 `apply_layer_boost`）：

```python
    async def search_memories_layered(self, query, user_id, owner_id,
                                      budget: dict | None = None) -> list:
        from app.services.memory_iteration import allocate_layer_budget
        budget = budget or allocate_layer_budget()
        out = []
        for layer, k in budget.items():
            if k <= 0:
                continue
            mems = await self._search_layer(query, user_id, owner_id, layer, k)
            out.extend(mems)
        return out
```

实现一个内部 `_search_layer(query, user_id, owner_id, layer, k)`：与 `search_memories` 相同（取候选→`rerank_candidates`→取 k），但 stmt 追加 `.where(Memory.memory_layer == layer)`，并对 principle 层在 rerank 前后用 `apply_layer_boost`（最简做法：principle 层直接 `k` 条按重要度+utility 取，不强依赖语义）。保持排除 `archived`。

- [ ] **Step 6: 接入注入点**（可选本任务或随后）：把 `agents.py` chat 与 `heartbeat` 思考的记忆注入从 `search_memories(limit=5)` 换成 `search_memories_layered(...)`，编号/记账逻辑沿用 P1。
- [ ] **Step 7: 跑相关测试 + 提交** — `feat(memory): layered retrieval with principle boost`

---

### Task 3: 做梦·语义提炼（相关簇 → semantic 记忆，本地 LLM）

**Files:** Modify `backend/app/services/sleep_cycle.py`；Test `backend/tests/test_sleep_cycle.py`（纯分簇逻辑）。

- [ ] **Step 1: 失败测试**（追加，测纯函数 `plan_related_clusters`）

```python
def test_plan_related_clusters_groups_min_size():
    from app.services.sleep_cycle import plan_related_clusters

    class M:
        def __init__(self, id, emb):
            self.id, self.embedding = id, emb
    items = [M(1, [1.0, 0.0]), M(2, [0.9, 0.1]), M(3, [0.85, 0.15]), M(9, [0.0, 1.0])]
    clusters = plan_related_clusters(items, threshold=0.7, min_size=3)
    assert len(clusters) == 1 and len(clusters[0]) == 3
```

- [ ] **Step 2: 跑，确认失败**
- [ ] **Step 3: 实现纯函数**（`sleep_cycle.py`，复用 P1 的 `cluster_by_similarity`）

```python
def plan_related_clusters(memories: list, threshold: float = 0.75, min_size: int = 3) -> list[list]:
    """Clusters of RELATED (not just duplicate) memories worth consolidating."""
    return [c for c in cluster_by_similarity(memories, threshold) if len(c) >= min_size]
```

- [ ] **Step 4: 跑通**
- [ ] **Step 5: 在 `run_sleep_cycle` 去重之后加语义提炼阶段**（本地 LLM）。提示词：

```python
_CONSOLIDATE_PROMPT = """你是记忆整理助手。把下面这一组相关的零碎记忆，概括成一条更高层的「印象/认识」（第三人称，1-2句，抓住共性，不要罗列）。

记忆组：
{cluster_text}

只输出概括后的那一句话。"""
```

逻辑：对 `plan_related_clusters` 的每个簇，仅当 episodic 层、且 owner 一致时，调本地 LLM 概括 → 用现有 `MemoryService.write_memory` 写一条 `memory_type="semantic"`、`memory_layer="semantic"` 的记忆（`importance_score` 取簇平均、`linked_memory_ids`=簇成员 id），并把簇成员 `consolidated_into` 指向它（后续按 P1 安全遗忘择机 archived）。`stats["promoted"] = 簇数`。写 `ActivityLog`。本地 LLM 不可用则跳过该阶段（不阻塞去重/遗忘）。

- [ ] **Step 6: 自包含异步集成测试**（sqlite-guard + `asyncio.run` + 假 LLM 返回固定句；同 P1 风格）：构造同 owner 的 ≥3 条相关 episodic（小维度 embedding），跑 `run_sleep_cycle(llm=假)`，断言生成了一条 `memory_layer=="semantic"` 且其 `linked_memory_ids` 含原成员。若 sqlite 向量列插入受限，退化为纯函数测试 + 导入冒烟（同 P1 Task 10 处理）。
- [ ] **Step 7: 提交** — `feat(memory): sleep cycle semantic consolidation (episodic→semantic)`

---

### Task 4: 做梦·洞见提纯 + principle 封顶/矛盾

**Files:** Modify `backend/app/services/sleep_cycle.py`、`memory_iteration.py`；Test `backend/tests/test_memory_iteration.py`、`test_sleep_cycle.py`。

- [ ] **Step 1: 失败测试**（封顶淘汰纯函数）

```python
def test_evict_lowest_confidence_caps_count():
    from app.services.memory_iteration import evict_lowest_confidence

    class P:
        def __init__(self, id, conf):
            self.id, self.importance_score = id, conf
    ps = [P(i, c) for i, c in enumerate([0.9, 0.2, 0.5, 0.1, 0.7])]
    keep, evict = evict_lowest_confidence(ps, cap=3)
    assert {p.id for p in keep} == {0, 2, 4}      # 0.9,0.5,0.7
    assert {p.id for p in evict} == {1, 3}        # 0.2,0.1
```

- [ ] **Step 2: 跑，确认失败**
- [ ] **Step 3: 实现纯函数**

```python
def evict_lowest_confidence(principles: list, cap: int = 20) -> tuple[list, list]:
    """Keep the top-`cap` principles by importance_score(=confidence); return (keep, evict)."""
    ordered = sorted(principles, key=lambda p: p.importance_score or 0.0, reverse=True)
    return ordered[:cap], ordered[cap:]
```

- [ ] **Step 4: 跑通**
- [ ] **Step 5: 洞见提纯阶段**（云端 LLM，门控）。在 `run_sleep_cycle` 末尾，按计数门控（见 Task 6 的计数器）触发。提示词：

```python
_INSIGHT_PROMPT = """你是洞见提炼师。从下面的记忆中，提炼这个小生命可泛化的「原则」——它从经历里学到的、关于自己/主人/你们关系的规律。

已有的原则（避免重复，可印证或修正）：
{existing_principles}

近期语义印象与重要情景：
{material_text}

输出 JSON 数组，每条：
{{"principle": "一句话原则（触发条件 → 倾向/结果）", "confidence": 0.0到1.0}}
最多 3 条，没有新原则就输出 []。只输出 JSON。"""
```

逻辑：调云端 LLM → 解析。对每条新 principle：与已有 principle（`memory_layer=="principle"`）比向量相似度——
- 高相似（印证）→ 已有那条 `importance_score = min(1.0, +0.1)`，不新建；
- 否则新建 `memory_type="principle"`、`memory_layer="principle"` 记忆；
- 矛盾（语义相反由 LLM 在调和提示中判断，简化版：相似但 confidence 差>0.3 时弱者 `symbolic_tags += ["conflict"]` 或降权）。
之后取该角色全部 principle，`evict_lowest_confidence(cap=20)`，被淘汰的设 `archived=True`。`stats["insights"]=新增数`。云端不可用则跳过。

- [ ] **Step 6: 提交** — `feat(memory): sleep cycle insight distillation + principle cap`

---

### Task 5: 人格 principle 驱动 + 漂移检测

**Files:** Modify `backend/app/services/memory_iteration.py`（纯函数）、`backend/app/services/memory_evolution.py`（`check_evolution`）；Test `tests/test_memory_iteration.py`。

- [ ] **Step 1: 失败测试**（漂移纯函数）

```python
def test_personality_drift_and_dampen():
    from app.services.memory_iteration import personality_drift, dampen_vector
    a = [1.0, 0.0]; b = [0.0, 1.0]
    assert personality_drift(a, a) < 0.01
    assert personality_drift(a, b) > 0.9
    d = dampen_vector(a, b, w=0.3)   # mostly a
    assert d[0] > d[1]
```

- [ ] **Step 2: 跑，确认失败**
- [ ] **Step 3: 实现**（`memory_iteration.py`）

```python
def personality_drift(old_emb: list[float], new_emb: list[float]) -> float:
    """0 = identical, →1 = very different (1 - cosine)."""
    return 1.0 - cosine_similarity(old_emb, new_emb)


def dampen_vector(old_emb: list[float], new_emb: list[float], w: float = 0.3) -> list[float]:
    """Take only a small step from old toward new."""
    return [(1 - w) * o + w * n for o, n in zip(old_emb, new_emb)]
```

- [ ] **Step 4: 跑通**
- [ ] **Step 5: 改 `check_evolution`**（`memory_evolution.py`）：
  1. 演化输入改为：该角色 `memory_layer=="principle"` 的 principle（按 confidence 取 top）+ 少量高分 semantic，替代原来大量 episodic 的 `memories_text`。
  2. 生成候选新人格后，对「旧 portrait_summary」与「新 portrait_summary」各自 `llm.embed`，算 `personality_drift`。
  3. `if drift > 0.35`：要求支撑该变化的 principle ≥ 2，否则**驳回本次演化**（return False）；若满足，则对人格的"情绪基调/描述"做保守处理（记录 drift，并在 portrait 里标注为渐变）。
  4. 演化前把当前 `portrait` 快照 append 到 `robot.portrait["history"]`（带 `created_at`），仅保留最近 N（如 10）份。
- [ ] **Step 6: 自包含异步测试**（可选，sqlite-guard）：构造一个角色 + 一条 principle，调 `check_evolution` 用假 LLM 返回突变人格，断言被驳回或阻尼且 `portrait["history"]` 有快照。受限则以纯函数测试 + 导入冒烟覆盖。
- [ ] **Step 7: 提交** — `feat(memory): principle-driven personality evolution with drift detection`

---

### Task 6: 接入做梦计数器 + 洞见门控

**Files:** Modify `backend/app/services/sleep_cycle.py`、`backend/app/services/heartbeat.py`。

- [ ] **Step 1: 计数门控**：在 `run_sleep_cycle` 用一个每角色计数器决定是否跑洞见提纯。最简：把 `sleep_count` 存进 `robot.current_status`（JSON），每次 +1；当 `sleep_count % 4 == 0` 且本轮 `stats["promoted"]>0`（有新语义材料）时才跑 Task 4 的洞见阶段。
- [ ] **Step 2: 验证导入** — `cd backend && .venv/bin/python3.12 -c "import app.services.sleep_cycle, app.services.heartbeat"`
- [ ] **Step 3: 提交** — `feat(memory): gate insight distillation by sleep-cycle cadence`

---

## 验收（P2 整体）

- [ ] 纯函数测试全绿：层预算/加成、related 分簇、principle 封顶、漂移/阻尼。
- [ ] 做梦后能从一组相关情景长出一条 `semantic` 记忆（带溯源 `linked_memory_ids`/`consolidated_into`）。
- [ ] 多轮做梦后生成 `principle` 记忆，且数量受 20 封顶。
- [ ] 检索能分层注入（principle 几乎常驻）。
- [ ] 人格演化由 principle 驱动；突变被阻尼/驳回；`portrait["history"]` 有快照。

## follow-up（不在 P2）

- P1 遗留：`M\d+` 正则误匹配收紧、去重回收窗口。
- P3：元调参（衰减/强化/阈值/层预算/权重自动调）。
- 跨角色 episodic 共享、矛盾原则的更强调和策略。
