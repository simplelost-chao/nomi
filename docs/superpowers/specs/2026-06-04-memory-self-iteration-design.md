# 记忆自迭代设计：记忆代谢（Memory Metabolism）

- 状态：草案 / 待评审
- 日期：2026-06-04
- 范围：Nomi 后端记忆系统（`backend/app/services/memory*.py`、`heartbeat.py`、`db/models.py`）

## 1. 目标

让记忆系统从「只会积累」进化为「会自我提炼」，实现四个自迭代方向：

1. **记忆越用越精** —— 自动整合、去重、遗忘冗余。
2. **检索越用越准** —— 用「记忆是否被实际使用」的反馈调整排序与重要度。
3. **人格越长越连贯** —— 从记忆提炼可泛化的「原则/洞见」反哺人格，并做漂移检测。
4. **参数自调** —— 衰减率/强化幅度/阈值等超参根据效果自动调节。

非目标：不重写现有实时机制（衰减、强化、reconsolidation、人格演化），而是在其上叠加。

## 2. 现状（基线）

现有实现已具备：语义检索（pgvector 余弦 / SQLite numpy 兜底）、指数衰减（每 5 分钟）、调用强化（+0.2 / 链接 +0.05）、reconsolidation（新记忆重新诠释旧记忆，写入 `reinterpretation`）、人格演化（≥10 条新记忆或有 reinterpretation 时触发 `check_evolution`）。

关键缺口（详见探索报告）：
- 检索纯余弦，无重要度/时近/有用度加权。
- 无整合、无去重、无真正的遗忘（衰减不删除）。
- `reinterpretation` 字段存了**从未被读取使用**。
- 心跳检索记忆后**未调用 `activate_memories()`**（强化不对称）。
- 无「记忆是否有用」的反馈信号 → 系统无法学习。

## 3. 架构总览

在现有**实时层**之上新增两个部件：

- **实时反馈信号**（每次交互，轻量）：捕获哪些被注入的记忆真正被使用。
- **做梦周期 `SleepCycle`**（空闲/每日触发）：一条分阶段流水线，集中做整合、提纯、遗忘、人格演化、元调参。

算力分层：**本地 ollama 干高频粗活（去重/整合/嵌入）**，**云端 DeepSeek/Claude 干关键提纯（洞见/人格）**。

```
实时:  对话 → 注入记忆(带编号) → LLM 回复(含 used_memory_ids) → 更新 utility_score / 强化
做梦:  触发 → [1去重] → [2整合] → [3提纯洞见] → [4重打分&遗忘] → [5人格演化] → [6元调参]
```

## 4. 组件详细设计

### 4.1 实时反馈信号（P1）

- 注入记忆进 prompt 时为每条标注序号/ID。
- 要求 LLM 在结构化回复中额外输出 `used_memory_ids`（实际参考了哪几条）。在 `agents/chat`、`orchestrator` 群聊、`heartbeat` 思考三处统一。
- 更新被检索记忆的字段：
  - `retrieved_count += 1`（每次被取出）
  - `useful_count += 1`（出现在 `used_memory_ids` 中）
  - `utility_score`：有用率的指数滑动平均，`utility = (1-α)·utility + α·(used?1:0)`，α≈0.3。
- **修复**：在 `heartbeat.py` 检索记忆后调用 `activate_memories()`，与 agent/chat 路径对齐。

### 4.2 做梦周期 `SleepCycle`（新服务 `backend/app/services/sleep_cycle.py`）

触发：复用心跳 loop 基建，新增 `_sleep_cycle_loop`。条件 = 用户空闲 ≥ 30 分钟（可配置）**或** 每日定时一次；逐机器人执行，记录 `last_sleep_at` 于 `robot.current_status`，避免重复跑。

流水线阶段：

| 阶段 | 逻辑 | 算力 | 阶段 |
|------|------|------|------|
| 1 去重 | 对自上次做梦以来的新记忆做向量聚类，余弦相似度 > 阈值（如 0.92）视为近重复 → 合并：保留最强一条，其余 `consolidated_into` 指向它、重要度累加、链接合并 | 本地嵌入 | P1 |
| 2 整合 | 对相关（中等相似）记忆聚类成簇 → 本地 LLM 将一簇概括为一条更高层记忆（`memory_type="consolidated"`），原始记忆置 `consolidated_into` | 本地 LLM | P1 |
| 3 提纯洞见 | 读取 top 重要度记忆 + 整合记忆 → 云端 LLM 提炼可泛化的「原则/规律」，存为 `memory_type="insight"` | 云端 LLM | P2 |
| 4 重打分&遗忘 | 重估重要度 `score = f(base, utility_score, recency, emotional)`；**安全遗忘**：仅当 `consolidated_into` 已设、或（低有用率 ∧ 老旧 ∧ 低重要度）三条全中，才 `archived=true`（软删，保留可恢复期后物理删） | 本地/纯计算 | P1 |
| 5 人格演化 | 把**洞见 + reinterpretation**（现有字段，启用！）一并喂给 `check_evolution`；加漂移检测 | 云端 LLM | P1→P2 |
| 6 元调参 | 跟踪指标 → 调超参（见 4.5） | 纯计算 | P3 |

每阶段写 `ActivityLog`（`event_type="sleep"` + `detail` 记录合并/删除/洞见数量），可追溯。

### 4.3 检索升级：混合排序（P1）

`MemoryService.search_memories` 改为混合分：

```
final = w1·cosine_sim + w2·importance_score + w3·utility_score + w4·recency_decay
```

- 先用向量取候选 Top-K'（K' > K，如 20），再用混合分重排取 Top-K。
- PostgreSQL 与 SQLite 兜底两路都改。
- P2 起：相关时优先注入高层 `insight`/`consolidated` 记忆，减少琐碎情景记忆占用。

### 4.4 数据模型改动（`db/models.py` + alembic 迁移）

`Memory` 新增字段：

| 字段 | 类型 | 含义 |
|------|------|------|
| `retrieved_count` | Integer 默认 0 | 被检索取出次数 |
| `useful_count` | Integer 默认 0 | 被 LLM 实际使用次数 |
| `utility_score` | Float 默认 0.0 | 有用率滑动平均 |
| `consolidated_into` | UUID 可空 | 被哪条整合/去重记忆吸收 |
| `archived` | Boolean 默认 false | 软删标记 |
| `memory_layer` | Text 默认 "episodic" | P2：episodic / semantic / principle |

不新建表：洞见/原则复用 `Memory`（`memory_type` 区分）；做梦状态进 `robot.current_status` JSON + `ActivityLog`。

### 4.5 元调参（P3）

跟踪指标：召回记忆的平均 `utility_score`（检索质量）、人格嵌入稳定度（演化是否过激）、库大小/冗余率。据此微调：衰减系数、强化 +Δ、去重/遗忘阈值、混合排序权重 `w1..w4`。采用小步长、带上下限的保守调整，全程记日志。

## 5. 安全护栏

- **安全遗忘**：见 4.2 阶段 4，绝不删除近期有用或高价值记忆；软删先行，保留恢复窗口。
- **人格漂移检测**：演化前后人格做嵌入距离比对，超阈值则抑制变化幅度，并保留人格历史快照可回滚。
- **幂等与可追溯**：做梦操作可重入，全部写 `ActivityLog`，便于调试与复盘。
- **降级**：云端不可用时，提纯/人格阶段跳过（不阻塞），下次做梦补做。

## 6. 分阶段交付

- **P1（基础闭环）**：实时反馈信号 + 修复心跳强化 + 混合检索 + 做梦阶段 1/2/4 + 启用 reinterpretation 进人格。数据迁移加除 `memory_layer` 外的新字段。→ 「记忆越用越精 + 检索越用越准」见效。
- **P2（记忆金字塔）**：`memory_layer` 层级 + 做梦阶段 3（洞见提纯）+ 分层检索 + 人格漂移检测。→「人格越长越连贯」。
- **P3（元学习）**：指标采集 + 元调参。→「参数自调」。

## 7. 已决策的设计选择

1. 反馈信号 = 让 LLM 自报 `used_memory_ids`（最便宜可靠），不另搞评估模型。
2. 遗忘 = 「先整合再删」的安全软删，不做激进遗忘。
3. 洞见/原则复用 `Memory` 表（`memory_type=insight`），不新建表。
4. 触发 = 空闲检测 + 每日，复用现有心跳 loop。

## 8. 风险与开放问题

- LLM 自报 `used_memory_ids` 可能不准（幻觉/漏报）→ 用滑动平均平滑，单次误差影响小；后续可加启发式校验。
- 整合/洞见的 LLM 概括可能引入失真 → 保留原始记忆（软删 + 恢复窗口），整合记忆标注来源 id。
- 本地 ollama 概括质量有限 → 关键阶段（洞见/人格）走云端；整合可按簇重要度择优上云。
- 做梦周期与现有 5 分钟衰减 loop 的协调 → 衰减保留，做梦的重打分覆盖衰减结果（做梦后为准）。

## 9. 验证思路

- 单元：去重合并、安全遗忘的删除条件、混合排序打分、utility 更新。
- 集成：模拟多轮对话 → 触发做梦 → 断言冗余被合并、低价值被软删、洞见生成、人格小步演化且未越过漂移阈值。
- 观测：`ActivityLog` 中 sleep 事件 + 指标随时间变化。
