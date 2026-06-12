# 工具技能系统设计（Tool Skills）

日期：2026-06-12
状态：已与用户确认方案，待实现

## 背景与目标

现有技能系统（`backend/app/services/skills.py`）是角色在心跳反思中自我演化出的"表达型"技能（讲冷笑话、编故事），执行时为纯 LLM 文本生成，无真实外部数据。

本设计新增一类**工具型技能**：接入真实外部 API（美食搜索、路线规划、天气、新闻热点、行情查询），让角色既能在聊天中真实回答用户问题，也能在心跳中自主获取真实信息并主动分享。

**成功标准：**
- 用户在聊天里问"附近有什么好吃的火锅"，角色回复中包含高德返回的真实餐厅
- 角色心跳中触发天气技能后，在群聊里主动分享真实天气
- 新增一个工具技能只需在注册表注册一个条目，聊天/心跳/前端展示零额外改动

## 已确认的决策

| 决策点 | 结论 |
|--------|------|
| 触发方式 | 聊天路径 + 心跳路径两者都做 |
| 第一批技能 | 高德三件套（美食/周边、路线、天气）+ 新闻热搜 + 行情（股票/币价/汇率） |
| 用户位置 | 配置默认城市（`NOMI_DEFAULT_CITY`），聊天中明说地点时覆盖 |
| 执行架构 | 方案 A：两段式路由（快模型意图识别 → 注册表执行 → 结果注入角色回复） |

### 否决的备选方案

- **原生 Function Calling**：默认 provider 是 claude-cli 子进程，无 API 级 tool use；需为每个 provider 单独适配，破坏现有 LLM 抽象层。
- **全部委托 Claude CLI Agent**：每次起子进程 5–15 秒，强绑定 claude-cli，调试黑盒。

## 架构

### 1. 工具注册表（核心新模块）`backend/app/services/tools/`

```
tools/
├── base.py        # Tool 数据类与 ToolResult
├── registry.py    # 注册表：get_tool(name) / all_tools() / build_router_prompt()
├── amap.py        # food_search / route_plan / weather（共用一个高德 Key）
├── news.py        # hot_news：复用 web_search.py 的 claude CLI WebSearch 子进程模式
└── finance.py     # quote：股票（新浪财经）/ 加密币（CoinGecko）/ 汇率（exchangerate-api）
```

**Tool 接口（统一契约）：**

```python
@dataclass
class Tool:
    name: str                 # 如 "food_search"
    display_name: str         # 如 "美食搜索"
    description: str          # 给意图路由 LLM 看的功能描述与参数说明
    trigger_hints: list[str]  # 聊天门控关键词 + 心跳 trigger_keywords 种子
    params_schema: dict       # 参数名 → 说明（供路由 prompt 生成）

    async def execute(self, params: dict) -> ToolResult: ...

@dataclass
class ToolResult:
    ok: bool
    summary: str              # 给 LLM 的文字摘要（注入角色回复 prompt）
    data: dict | None         # 结构化原始数据（日志/调试用）
    error: str | None
```

### 2. 聊天路径

```
用户消息
  → ① 关键词门控：消息命中任一工具的 trigger_hints 才进入下一步
      （避免每条消息都付一次路由 LLM 调用）
  → ② 意图路由：DeepSeek flash（已有快模型通道）
      输入：工具清单（registry.build_router_prompt()）+ 用户消息 + 默认城市
      输出 JSON：{"tool": "food_search", "params": {...}} 或 {"tool": null}
      关键约束：区分"查询意图"与"情绪表达"（"我好想吃火锅啊"≠ 搜索请求）
  → ③ 注册表执行：asyncio 超时 10s
  → ④ 结果注入角色回复 prompt：
      "你刚用「X」查到以下真实信息：{summary}。用你的语气回答。
       只能使用上面查到的信息，查不到/失败就如实说，不许编造。"
```

地点参数：路由 LLM 从用户消息提取；未提及时用 `NOMI_DEFAULT_CITY`。

### 3. 心跳路径

- `RobotSkill` 表新增字段 `tool_name: str | None`（一条 alembic migration）
- 种子脚本：为角色注入内置工具技能（name/description/trigger_keywords 来自注册表的 display_name/description/trigger_hints，`skill_type="tool"`）
- `execute_skill()`（skills.py:131–167）增加路由分支：
  - `skill.tool_name` 非空 → 注册表执行（params 由快模型从 thought 上下文提取，城市用默认值）→ 主 LLM 用人设语气包装 ToolResult.summary
  - 为空 → 走原有纯 LLM 生成逻辑
- 事件流不变：照常广播 `skill_used`、写 ActivityLog、更新 usage_count。前端 group-chat 与 admin 技能 tab 零改动。

### 4. 配置（`app/config.py` Settings + `.env`）

```bash
NOMI_AMAP_API_KEY=        # 高德开放平台 Web 服务 Key（免费，个人版日配额数千次）
NOMI_DEFAULT_CITY=北京     # 位置默认值
```

新闻走已有 claude CLI（无新 Key）；新浪财经/CoinGecko/exchangerate-api 免 Key 或免费层。

## 错误处理

- 所有外部 HTTP 调用 10 秒超时（aiohttp）
- API 失败/超时/空结果：ToolResult.ok=False，角色以人设口吻如实说"没查到"；prompt 硬性约束禁止编造
- 路由 LLM 输出非法 JSON：视为 tool=null，正常走聊天，不阻塞回复
- 高德配额耗尽（返回 infocode）：同失败处理，日志记 warning

## 测试

- 每个工具：mock HTTP 的单元测试（成功/失败/空结果/超时）
- 意图路由：一组"该触发/不该触发"用例（查询 vs 情绪表达、带地点 vs 不带地点）
- 端到端手测：聊天问美食/路线/天气/新闻/股价各一次；手动触发心跳验证自主分享

## 实现范围（第一批）

1. tools 模块骨架（base/registry）+ 高德三件套
2. 聊天路径（门控 + 路由 + 注入）
3. 心跳路径（migration + 种子 + execute_skill 路由）
4. news.py 与 finance.py
5. 测试与 .env.example 更新

不在本批范围：前端定位、提醒/闹钟技能、多轮工具调用（先查地点再查路线的链式调用）。
