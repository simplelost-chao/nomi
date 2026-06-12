"""Central registry: chat router and heartbeat skills both resolve tools here."""

from app.services.tools.base import Tool

_TOOLS: dict[str, Tool] = {}


def register(tool: Tool) -> Tool:
    _TOOLS[tool.name] = tool
    return tool


def get_tool(name: str) -> Tool | None:
    return _TOOLS.get(name)


def all_tools() -> list[Tool]:
    return list(_TOOLS.values())


def gate_match(text: str) -> bool:
    """Cheap keyword gate so we don't pay a router-LLM call for every message."""
    if not text:
        return False
    return any(hint in text for tool in _TOOLS.values() for hint in tool.trigger_hints)
