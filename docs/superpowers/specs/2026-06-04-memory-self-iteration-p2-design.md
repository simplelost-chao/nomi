# 记忆自迭代 P2 设计：记忆金字塔与人格连贯

- 状态：草案 / 待评审
- 日期：2026-06-04
- 前置：P1（反馈信号 + 混合检索 + 做梦周期去重/安全遗忘）已实现，见 `2026-06-04-memory-self-iteration-design.md` 与 P1 计划。
- 目标方向：**人格越长越连贯**。

## 1. 目标

把 P1 的扁平记忆显式长成三层金字塔，让做梦周期把记忆"往上提炼"，并让人格只由提炼后的"原则"驱动 + 漂移检测，从而：

1. 记忆有层次：情景 → 语义 → 原则，越上越抽象稳定。
2. 角色从经历中提炼出**可泛化的原则**，行为更有一致的"价值观"。
3. 人格**渐变且有据可依**，不会突变/精神分裂。

非目标：元调参（P3）；不重写 P1 已有机制，只在其上叠加。

## 2. 记忆金字塔

新增字段 `Memory.memory_layer`，取值：

| 层 | 含义 | 来源 | 量级 | 衰减/遗忘 |
|----|------|------|------|-----------|
| `episodic` 情景 | 单个事件 | P1 写入路径 | 高 | 易衰减、可遗忘 |
| `semantic` 语义 | 从多条情景抽象的印象/模式 | 做梦·语义提炼（本地 LLM） | 中 | 较耐久 |
| `principle` 原则 | 关于自我/主人/关系的可泛化规律 | 做梦·洞见提纯（云端 LLM，低频） | 极低（封顶 20/角色） | 极耐久，几乎不遗忘 |

提炼方向自下而上；检索与人格演化自上而下使用。principle/semantic 复用 `Memory` 表（`memory_type` + `memory_layer` 区分），溯源用现有 `consolidated_into` / `linked_memory_ids`。

## 3. 做梦周期新增两阶（接在 P1 的去重之后）

### 3.1 语义提炼（每次做梦 · 本地 LLM）
P1 只合并近重复（余弦 ≥ 0.92）。P2 增加对**相关簇**（用较低阈值，如 0.75）的处理：
```
对每个 size ≥ 阈值(如 3) 的相关簇：
    本地 LLM 把整簇概括成一条 semantic 记忆（memory_layer="semantic"）
    新 semantic.linked_memory_ids = 簇成员 id
    簇成员 episodic.consolidated_into = 新 semantic.id（保留溯源；按 P1 安全遗忘择机 archived）
```
这是 P1 中故意推迟的"LLM 整合成更高层记忆"，落在此处。

### 3.2 洞见提纯（低频 · 云端 LLM）
触发条件（默认）：`自上次提纯以来的做梦次数 ≥ 4`（约每日）**且** `存在 ≥ N 条新 semantic 记忆`。
```
输入：top semantic 记忆 + 高分 episodic + 已有 principle 列表
云端 LLM 提炼可泛化原则，每条 = {触发条件, 倾向/结果, confidence}
去重/调和（与已有 principle 比向量相似度）：
    印证已有 → 该 principle 的 importance_score(=confidence) 上调
    与已有矛盾 → 标记 symbolic_tags 含 "conflict"；保留两者（内在张力），
                仅当一方 confidence 显著高(差 > 0.3)时由下次提纯调和（弱者降权/归档）
封顶：每角色 principle 数 ≤ 20；超出则淘汰最低 confidence 的
```

每阶段写 `ActivityLog`（`event_type="sleep"`，detail 记 promoted/insights 数）。

## 4. 分层检索

`MemoryService` 增加分层预算检索：注入 prompt 时按层取，默认预算
`principles=2, semantic=2, episodic=2`（可配）。principle 在混合排序上加一个常驻加成（它们是"人格公理"，应几乎总被注入）。各层内部仍用 P1 的混合分排序，排除 `archived`。纯逻辑（预算分配 + principle 加成）放进可单测的 helper。

## 5. 人格连贯（P2 的核心）

### 5.1 人格只由 principle 驱动
`check_evolution` 改为：演化输入主要是**已提炼的 principle**（+ 少量高分 semantic），不再直接喂大量零碎 episodic。输入连贯 → 输出稳定。

### 5.2 漂移检测
```
演化前：旧人格描述、候选新人格描述各自嵌入
drift = 1 - cosine(old_emb, new_emb)
if drift > 阈值(默认 0.35):           # 突变，可疑
    候选 = 阻尼混合(旧, 新, w=0.3)      # 只走一小步
    且要求该变化有 ≥ 2 条 principle 支撑，否则驳回本次演化
存一份 personality 快照进 robot.portrait["history"]（带时间戳，可回滚），保留最近 N 份
```

`drift` 计算与阻尼判定是纯函数，可单测；嵌入与落库在服务层。

## 6. 数据改动

- `Memory` 加 `memory_layer: Text default "episodic"`（alembic 迁移）。
- principle 的 confidence 复用 `importance_score`；触发条件/倾向写进 `content`（结构化前缀，如 `"[触发] ... [倾向] ..."`）或 `symbolic_tags`。
- 人格历史快照存 `robot.portrait["history"]`（JSON 数组），**不新建表**。

## 7. 成本与节奏（延续 P1 分层算力）

- 语义提炼：本地 ollama，每次做梦（6h）。
- 洞见提纯：云端 DeepSeek/Claude，低频（默认每 ~24h 且有新材料）。
- 漂移检测嵌入：本地嵌入模型。

云端不可用 → 跳过洞见/人格阶段，下次补。

## 8. 已决策（默认值，可改）

1. 洞见频率 = 每 4 次做梦且有新 semantic 材料。
2. 漂移超阈 = 阻尼小步 + 需 ≥2 principle 背书，否则驳回。
3. principle 封顶 = 20/角色，满则淘汰最低 confidence。
4. 矛盾原则 = 默认保留为"内在张力"，仅强证据（confidence 差 >0.3）时调和。

## 9. 风险与开放问题

- 本地 LLM 语义概括质量有限 → 语义层标注来源 id，可回溯；必要时高重要度簇上云。
- 洞见可能提炼出错误/过拟合的原则 → confidence + 漂移背书要求 + 矛盾保留，避免单条原则独断人格。
- principle 封顶可能误淘汰偶发但重要的原则 → 淘汰只按 confidence，且被印证会持续升 confidence；可设保护期。
- 分层预算可能挤掉关键 episodic → 预算可配；后续可按查询动态调整。

## 10. 验证思路

- 单元：层预算分配、principle 加成排序、drift 距离与阻尼、principle 封顶淘汰、矛盾标记。
- 集成：构造多条相关情景 → 做梦 → 断言生成 semantic（带溯源）；多次做梦触发洞见 → 断言生成 principle 且封顶生效；构造突变人格 → 断言被阻尼/驳回且历史快照存在。
- 观测：`ActivityLog` 中 promoted/insights 计数；人格历史随时间的 drift 曲线平滑。

## 11. 分阶段（P2 内部建议落地顺序）

1. memory_layer 迁移 + 分层检索（先让"金字塔"可读可取）。
2. 语义提炼（做梦长出 semantic 层）。
3. 洞见提纯 + principle 封顶/矛盾处理。
4. 人格 principle 驱动 + 漂移检测（连贯性收口）。
