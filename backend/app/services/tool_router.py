"""Two-stage tool routing for chat: keyword gate -> flash-LLM intent -> execute.

关键设计：区分「查询意图」和「情绪表达」——
"哪里有好吃的火锅" 是查询，"我好想吃火锅啊" 是抒情，后者不触发工具。
"""

import asyncio

from app.services.llm.base import BaseLLM
from app.services.tools import registry
from app.services.tools.base import ToolResult


def _build_router_prompt(user_message: str) -> str:
    tool_lines = []
    for t in registry.all_tools():
        params = "；".join(f"{k}（{v}）" for k, v in t.params_schema.items())
        tool_lines.append(f"- {t.name}：{t.description}。参数：{params}")
    tools_str = "\n".join(tool_lines)
    return f"""你是一个工具路由器。判断用户消息是否需要调用工具获取真实信息。

可用工具：
{tools_str}

判断规则：
1. 只有用户在【请求真实信息】时才调用工具（如"附近有什么好吃的"、"明天天气怎么样"）
2. 情绪表达、闲聊、回忆【不】调用工具（"我好想吃火锅啊"是抒情不是查询）
3. 参数从用户消息里提取；提取不到的留空字符串
4. 不确定就不调用（tool 输出 null）

用户消息：「{user_message}」

只输出合法 JSON，不要其他文字：
{{"tool": "工具名或null", "params": {{"参数名": "值"}}}}"""


async def route_and_execute(
    user_message: str, llm_flash: BaseLLM
) -> tuple[str, ToolResult] | None:
    """Returns (tool display_name, result) if a tool fired, else None.

    Never raises — any failure degrades to None (chat proceeds without tools).
    """
    if not registry.gate_match(user_message):
        return None

    try:
        decision = await llm_flash.generate_structured(
            messages=[{"role": "user", "content": _build_router_prompt(user_message)}],
            system_prompt="你是工具路由器，只输出 JSON。",
            temperature=0.1,
        )
    except Exception as e:
        print(f"[tool_router] Router LLM failed: {e}")
        return None

    tool_name = decision.get("tool") if isinstance(decision, dict) else None
    if not tool_name or str(tool_name).lower() == "null":
        return None
    tool = registry.get_tool(str(tool_name))
    if not tool:
        return None

    params = decision.get("params") or {}
    if not isinstance(params, dict):
        params = {}
    try:
        result = await asyncio.wait_for(tool.execute(params), timeout=tool.timeout)
    except asyncio.TimeoutError:
        result = ToolResult(ok=False, error="查询超时了")
    except Exception as e:
        result = ToolResult(ok=False, error=f"查询失败：{e}")
    return tool.display_name, result
