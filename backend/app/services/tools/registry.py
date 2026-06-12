"""Central registry: chat router and heartbeat skills both resolve tools here."""

from app.services.tools.base import Tool

_TOOLS: dict[str, Tool] = {}
_disabled: set[str] = set()


def register(tool: Tool) -> Tool:
    _TOOLS[tool.name] = tool
    return tool


def get_tool(name: str) -> Tool | None:
    return _TOOLS.get(name)


def all_tools() -> list[Tool]:
    return list(_TOOLS.values())


def is_enabled(name: str) -> bool:
    return name not in _disabled


def set_tool_state(name: str, enabled: bool) -> None:
    if enabled:
        _disabled.discard(name)
    else:
        _disabled.add(name)


def set_disabled(names: set[str]) -> None:
    _disabled.clear()
    _disabled.update(names)


def enabled_tools() -> list[Tool]:
    return [t for t in _TOOLS.values() if t.name not in _disabled]


def gate_match(text: str) -> bool:
    """Cheap keyword gate so we don't pay a router-LLM call for every message."""
    if not text:
        return False
    return any(hint in text for tool in enabled_tools() for hint in tool.trigger_hints)
