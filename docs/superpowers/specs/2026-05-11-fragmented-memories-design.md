# Fragmented Memories: 碎片化记忆系统重构

## 问题

当前系统为每个物品生成 3-12 段长记忆（300-4000 字/段），总共约 9 段回忆。问题：
1. **数量太少** —— 活了 10 年的物品只有 9 段回忆，太单薄
2. **每段太长** —— 像散文不像记忆，真实记忆是碎片化的
3. **缺乏连续性** —— 每段记忆独立生成，物理状态（裂痕、磨损）和情感状态不会自动延续

## 目标

9 段长文 → **~80 段短片段**，每段 80-250 字，带连续状态保证前后一致。

## 设计

### 数量与长度规则

| 属性 | 旧 | 新 |
|---|---|---|
| 数量 | 3-12（LLM 自由选） | `age × 8`（下限 20，上限 120） |
| 每段长度 | 300-4000 字 | 80-250 字 |
| 类型 | vivid/fragment/feeling（决定长度） | 保留，只影响语气不影响长度 |
| Summary | 每段生成 80-120 字摘要 | 去掉（content 本身够短） |

### 生成方式：分批 + ongoing_state

取消两步流程（选瞬间 → 逐个展开），改为按时间段分批生成。

#### 时间段划分

根据 age 自动切分：
- age <= 3: 2 批
- age <= 8: 3 批
- age <= 15: 4 批
- age <= 30: 5 批
- age > 30: 6 批

每批覆盖一段时间，批内记忆数 = 总数 / 批数（约 10-20 条/批）。

#### ongoing_state

每批输出一个 ongoing_state JSON，传给下一批作为上下文：

```json
{
  "physical": ["左侧有一道裂痕，是三岁那年摔的", "漆面开始发黄"],
  "emotional": ["对黑暗已经习惯", "开始享受被遗忘的安静"],
  "relationships": ["主人是一个女孩，叫小雨", "跟书架上的时钟是邻居"],
  "environment": ["住在卧室的书架上"]
}
```

**规则**：
- 新状态覆盖旧状态（搬家后 environment 更新）
- 物理状态只增不减（裂痕不会消失，除非修复且明确说明）
- 关系可以变化（主人换了、邻居被送走）

#### 单批 prompt 输入/输出

**输入**：
- 物品信息（名字、描述、性格、愿望、恐惧）
- life_theme（第一批时由 LLM 同时生成）
- 时间范围（如 "0-3岁"）
- 目标记忆数（如 15 条）
- ongoing_state（第一批为空）
- 上一批最后 3 条记忆的 content（重叠上下文，保证衔接）

**输出 JSON**：
```json
{
  "life_theme": "这一生的主题（仅第一批输出）",
  "memories": [
    {
      "time": "刚从工厂出来",
      "approximate_age": 0,
      "title": "第一次感受到空气",
      "emotional_core": "好奇",
      "content": "80-250字的记忆正文",
      "memory_type": "fragment",
      "importance": 0.7
    }
  ],
  "ongoing_state": {
    "physical": [...],
    "emotional": [...],
    "relationships": [...],
    "environment": [...]
  }
}
```

### Prompt 设计要点

沿用现有的物品感知规则（材质决定感知、不用"光"开头等），新增：

1. **短记忆指导**：
   - 每段 80-250 字，像一个画面、一个触感、一句话
   - 不是散文，不是叙事，是记忆碎片
   - 有的只有感官（"那天的雨声很大"），有的有事件（"她把我从地上捡起来"）
   - 最重要的记忆也不超过 250 字

2. **连续性指导**：
   - ongoing_state 里的物理状态必须在后续记忆中保持一致
   - 如果状态变化（搬家、修复、换主人），必须有对应的记忆描述这个变化
   - 不能凭空出现或消失

3. **密度变化**：
   - 被频繁使用的时期 → 记忆密集
   - 被遗忘在角落的岁月 → 只有 1-2 条模糊感受
   - LLM 在目标数量范围内自由分配密度

### DB Schema 变化

`YearlyMemory` 表：
- **新增** `batch_index: int | None` —— 属于第几批（0-based），方便调试和重新生成
- 其余字段不变
- `memory_summary` 字段保留但不再写入（向后兼容）
- `memory_content` 内容变短（80-250 字）

不需要新表。Migration: 加一列 `batch_index`。

### 创建流程变化

```
旧流程：
  Step 3: build_life_moments_prompt → 1 次 Claude → 得到 moments[]
  Step 4: 对每个 moment → build_moment_detail_prompt → N 次 Claude
        + build_moment_summary_prompt → N 次 DeepSeek
  Step 5: build_portrait_prompt → 1 次 Claude

新流程：
  Step 3+4 合并为 "memories":
    for batch in batches:
      build_batch_memories_prompt(..., ongoing_state) → 1 次 Claude
      → 得到 memories[] + 新 ongoing_state
      → 写入 DB
  Step 5: build_portrait_prompt → 1 次 Claude（用 content 代替 summary）
```

**调用次数**：旧 ~1+2N 次（N≈9 → ~19 次），新 ~K+1 次（K≈5 → ~6 次）。更快更便宜。

### Portrait 调整

输入从 summary 改为 content（因为 content 已经够短）：

```python
# 之前
memories_text += f"【{time}】（清晰度 {pct}%）{summary}"
# 之后
memories_text += f"【{time}】（清晰度 {pct}%）{content}"
```

80 条 × 250 字 = 20,000 字 context，完全在 Claude 能力范围内。

### Regenerate 兼容

`regenerate.py` 的逻辑已经是 "删除旧 YearlyMemory → 重新生成"，改为调用新的批量生成函数即可。

### 前端影响

`YearlyMemoryOut` schema 不变。前端展示从 9 段长文变为 ~80 段短片段。
时间线展示天然适合短条目——如果需要，前端可以按 age 分组展示，但这不在本次 scope 内。

### 进度追踪

创建时的进度显示改为按批次：
- `memories_total`: 总目标记忆数
- `memories_done`: 已完成批次的记忆数累计
- `current_memory`: 当前批次描述（如 "第2批：3-6岁"）

## 涉及文件

| 文件 | 变化 |
|---|---|
| `backend/app/prompts/creation.py` | 删除 `build_life_moments_prompt`、`build_moment_detail_prompt`、`build_moment_summary_prompt`，新增 `build_batch_memories_prompt` |
| `backend/app/api/robots.py` | Step 3+4 合并，改为循环调用批量生成 |
| `backend/app/api/regenerate.py` | 同上 |
| `backend/app/db/models.py` | YearlyMemory 加 `batch_index` 列 |
| `backend/app/schemas.py` | 无变化 |
| `alembic/versions/` | 新 migration: add batch_index |

## 不做的事

- 不改 heartbeat Memory 表（那是运行时记忆，跟这次无关）
- 不改前端展示（保持现有时间线，只是数据变了）
- 不改 memory_evolution.py（那是运行时记忆的衰减/重构，跟 YearlyMemory 无关）
- 不做记忆合并/压缩（以后可以考虑）
