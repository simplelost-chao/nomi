# 提醒/闹钟技能 + 工具开关 设计

日期：2026-06-12
状态：用户已确认（含补充需求：所有工具技能可随时开关）

## 目标

1. 用户在聊天里说"明早八点叫我起床"→ 角色确认并到点主动提醒（应用内气泡 + TTS 语音，桌面端/网页通用）
2. 所有工具技能（含已有 7 个 + 新增 3 个提醒工具）可在 admin 面板随时开关，运行时生效，不需重启

## 设计决策

| 决策点 | 结论 |
|--------|------|
| 设置入口 | 提醒 = 第 8 组工具（set_reminder / list_reminders / cancel_reminder），复用现有意图路由 |
| 时间解析 | 路由 prompt 注入当前时间（Asia/Shanghai），LLM 输出 "YYYY-MM-DD HH:MM" 本地时间；存储转 UTC naive（遵循库内 utcnow 惯例） |
| 触发机制 | heartbeat 新后台循环 `_reminders_check_loop()`（30s），仿照 `_memory_decay_loop` |
| 提醒通道 | 复用现有 `message` 事件 + Message 表写入 → 前端零改动，气泡/字幕/TTS 自动生效 |
| 提醒角色 | reminders.robot_id 可空；创建时不强绑，触发时随机选一个活跃角色用人设语气提醒 |
| 重复 | 第一版仅 once / daily；错过的提醒下次检查时补触发 |
| 工具开关存储 | 新表 `tool_settings(tool_name PK, enabled)`；registry 内存缓存，启动时水合，admin API 更新 DB+缓存 |
| 开关生效面 | 聊天路由（门控+prompt+执行）和心跳 `_execute_tool_skill` 都过滤禁用工具；已设置的提醒不受 set_reminder 开关影响（照常触发） |
| 自主性标记 | Tool 新增 `autonomous: bool = True`；提醒三件套为 False（不种子进 RobotSkill，角色不会自己给自己设提醒） |
| 开关 UI | `backend/app/admin_panel.html` 头部加"🔧 工具开关"按钮 → 模态列出所有工具 + 开关；GET/PUT `/api/admin/tools` |

## 范围外（YAGNI）

每周/自定义重复、系统级通知、提醒联动其他工具（如顺带报天气）、per-robot 工具开关。

## 数据表

```
reminders: id, robot_id(FK nullable), title, trigger_time(UTC naive), repeat('once'|'daily'),
           is_active(bool), last_triggered_at(nullable), created_at
tool_settings: tool_name(text PK), enabled(bool default true), updated_at
```

## 错误处理

- 路由解析不出时间 → set_reminder 返回 ok=False，角色如实说"没听懂时间"
- cancel 关键词匹配多条 → 返回列表让用户再说具体些
- 检查循环异常 → 打日志继续，绝不让循环退出
- 工具被禁用 → 聊天路由视为不存在；心跳技能静默跳过

## 测试

- 核心逻辑（services/reminders.py：创建/查到期/推进 daily/取消）用 sqlite 会话单测
- 工具开关：registry 过滤 + 禁用后路由/心跳行为单测
- E2E：admin 开关实测；设 1 分钟后提醒，验证事件广播 + Message 落库
