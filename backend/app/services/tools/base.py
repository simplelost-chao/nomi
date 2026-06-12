"""Tool skills — real external-API-backed skills shared by chat and heartbeat paths."""

from dataclasses import dataclass
from typing import Awaitable, Callable


@dataclass
class ToolResult:
    ok: bool
    summary: str = ""          # 给 LLM 的文字摘要（注入角色回复 prompt）
    data: dict | None = None   # 结构化原始数据（日志/调试用）
    error: str | None = None


@dataclass
class Tool:
    name: str                  # 机器名，如 "food_search"
    display_name: str          # 展示名，如 "美食搜索"
    description: str           # 给路由 LLM 的功能描述
    trigger_hints: list[str]   # 聊天门控关键词；也是心跳技能的 trigger_keywords 种子
    params_schema: dict        # 参数名 -> 中文说明（用于生成路由 prompt）
    execute: Callable[[dict], Awaitable["ToolResult"]]
    timeout: int = 10          # 执行超时秒数（claude CLI 类工具需调大）
