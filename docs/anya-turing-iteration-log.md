# Anya 图灵测试迭代日志

目标:让 Anya 在对话/自主行为中更像真实的人(《间谍过家家》阿尼亚),减少 AI 痕迹、保持人设与记忆一致。
自主迭代;每轮记录:测试 → 发现的问题 → 改动 → 验证。

---
## Cycle 1
**测试**:5 条探针对话(自我介绍/记忆/AI陷阱/数学代码/知识) + reflect 触发。
**发现的问题**:
1. 🔴 记忆标签泄漏 —— 回复结尾出现 `(M1,M3)`(P1 反馈信号的编号漏进了用户可见文本)。
2. 🟠 reflect 跑偏 —— 只塞最痛的过往记忆 + "写深刻反思",生成成人式忧郁、且违背原作(她家人是爱她的)。
3. 🟠 无对话连续性 —— 问"我叫什么名字"答"你叫(你的名字)"占位符(agent chat 无状态,没带上一轮)。→ Cycle 2 处理
**改动**:
- `agents.py`:解析 reply 后用正则剥掉 `(M\d+)` 标签(保留 `_raw_content` 给反馈提取)。
- `heartbeat.py` reflect prompt:锚定"现在被爱着/安全"+ 用角色口吻 + 禁止成人式忧郁反思。
**验证**:标签消失;反思变回童真且符合原作。✅

## Cycle 2
**测试**:带 conversation_id 的连续对话 + 6 轮自然对话 + thought 触发调试。
**发现**:
1. ✅ 对话连续性带 conversation_id 时正常(记住名字+喜好)——之前的"占位符"是测试没传 cid 的假象,非 bug。
2. 对话质量高:共情自然、人设稳、长度合理,无急需修的对话问题。
3. 🔴 `thought` 永远返回空 —— 真因:`THOUGHT_PROMPT` 含 `{current_conversation}` 占位符,但 `_generate_thought.format()` 没传 → KeyError 被吞 → None。
4. 🟠 `THOUGHT_PROMPT` 开头"你是一个有生命的物品"——物件框架,对角色不合适。
**改动**:
- `api/heartbeat.py`:`_generate_thought` 补 `current_conversation=""`。
- `services/heartbeat.py`:`THOUGHT_PROMPT` "有生命的物品" → "你就是 {name}，用自己的性格口吻"。
- `tools/heartbeat_harness.py`:对话改为带 conversation_id(更真实)。
**验证**:thought 能产出在人设、且引用近期对话的想法。✅

