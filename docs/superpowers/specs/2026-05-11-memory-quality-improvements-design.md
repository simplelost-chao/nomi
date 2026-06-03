# 记忆质量改进 + 关系系统 + Portrait 展示 + 声音修复

## 问题

1. **记忆太同质化**：63 条记忆几乎都是"被拿起来泡茶"的变体，缺少人生转折和事件多样性
2. **Portrait 展示单薄**：后端生成了丰富的 portrait 数据，前端只显示性格词和 origin_story
3. **缺少关系系统**：记忆中出现了人和物，但没有结构化的关系数据
4. **声音按钮不工作**：TTS URL 硬编码了外部域名

## 设计

### 1. 记忆多样性（Prompt 改进）

在 `build_batch_memories_prompt` 的 system prompt 中新增事件类型引导：

```
## 一生应该有的经历类型（不是每种都要有，但不能只有一种）

- 环境变化：搬家、换房间、被带出门、旅行、被存进箱子
- 人的变化：换主人、新的家庭成员、客人、小孩、宠物
- 意外事件：摔落、被修补、被误用、丢失又找回、差点被扔掉
- 时代印记：周围物品的更替、声音的变化（收音机→电视→手机）、装修
- 关系时刻：被当礼物送出、被争抢、被分享、被嫉妒、被忽视
- 仪式感：生日、节日、搬新家、告别
- 内心转折：第一次意识到自己老了、接受被遗忘、理解主人的选择

不要让所有记忆都是同一种类型的变体。如果连续 3 条记忆都是"被拿起来泡茶"，
说明你在重复而不是在创造一段人生。
```

**文件**：`backend/app/prompts/creation.py`

### 2. 关系系统

#### 数据结构

`ongoing_state.relationships` 从文本列表变为结构化数组：

```json
{
  "relationships": [
    {
      "name": "小雨",
      "role": "主人",
      "status": "亲密",
      "memories": [
        "她第一次把我从箱子里拿出来，手指在裂口上摸了一下",
        "深夜她对我说'就你还一直在'",
        "她开始用新杯子，我被放进了高柜子",
        "过了很久她又把我拿出来，擦掉灰尘"
      ]
    },
    {
      "name": "白色马克杯",
      "role": "邻居",
      "status": "已离开",
      "memories": [
        "我们并排站在架子上，它比我高半个头",
        "有一天它的位置空了，不知道是碎了还是被收走了"
      ]
    }
  ]
}
```

#### Prompt 变更

在 `build_batch_memories_prompt` 的 ongoing_state 输出格式中，将 `relationships` 从 `string[]` 改为上述结构。新增指导：

```
relationships 规则：
- 每个关系有 name、role、status、memories
- role：主人/家人/朋友/邻居/陌生人/宠物 等
- status：亲密/熟悉/疏远/已离开/新认识 等
- memories：这段关系中的关键时刻（简短，每条一句话，按时间顺序）
- 新的互动追加到 memories 列表
- 关系状态可以变化（亲密→疏远→重新亲密）
- 人离开了也要保留这个关系，status 标为"已离开"
```

#### 存储

创建完成后，从最后一批 `ongoing_state.relationships` 提取，存入 `Robot` 表新字段：

```python
# models.py - Robot 表
relationships_snapshot: Mapped[list | None] = mapped_column(JSONB)
```

需要一个 alembic migration 加这个字段。

在 `_run_creation` 和 `regenerate_memories` 的循环结束后：

```python
robot.relationships_snapshot = ongoing_state.get("relationships", []) if ongoing_state else []
```

#### 前端展示

在 robot detail 页面加一个"关系"区块，展示关系列表。每个关系可展开查看 memories 时间线。

**文件**：
- `backend/app/prompts/creation.py`
- `backend/app/db/models.py`（新字段）
- `backend/app/api/robots.py`（写入 snapshot）
- `backend/app/api/regenerate.py`（写入 snapshot）
- `backend/app/schemas.py`（RobotOut 加字段）
- `frontend/src/app/robots/[id]/page.tsx`（展示）
- `frontend/src/lib/types.ts`（类型）
- `alembic/versions/`（migration）

### 3. Portrait 展示

`robot.portrait` 已有完整数据，前端改为展示：

| 字段 | 展示方式 |
|---|---|
| `current_self_description` | 自我描述卡片，200-300 字 |
| `remembered_facts` | 列表："还记得的事" |
| `faded_impressions` | 列表（淡色）："模糊的印象" |
| `personality_now.how_it_speaks` | 说话方式描述 |
| `personality_now.emotional_baseline` | 情绪基调标签 |
| `inner_world.what_it_values` | 珍视 |
| `inner_world.what_it_fears_now` | 恐惧（可能跟年轻时不同） |
| `inner_world.unresolved` | 放不下的事 |
| `inner_world.wisdom` | 这一生教会它的事 |

替换现在的简陋 portrait 区域。用分区卡片呈现，不需要全部展开，用折叠或 tab。

**文件**：`frontend/src/app/robots/[id]/page.tsx`

### 4. 声音修复

前端 TTS URL 硬编码了 `https://nomi-api.zhuchao.life/api/tts/speak`，改为走前端 proxy：`/api/tts/speak`。

同时检查 TTS endpoint 是否正常返回音频。

**文件**：`frontend/src/app/robots/[id]/page.tsx`

## 不做的事

- 不改 `Relationship` 表（那是 heartbeat 运行时关系，用途不同）
- 不改 heartbeat/memory_evolution 逻辑
- 不改 Memory 表
- 不做关系图谱可视化（先用列表）
