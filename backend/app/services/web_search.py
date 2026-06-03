"""Web Search for robots — uses Claude CLI with WebSearch tool."""

import asyncio
import json

from app.db.models import Robot


async def search_topic(robot: Robot, query: str) -> dict | None:
    """Search the web via Claude CLI WebSearch, then summarize with robot's personality."""
    personality = robot.personality or []
    if isinstance(personality, dict):
        personality = list(personality.values())
    personality_str = ", ".join(str(p) for p in personality[:4])

    prompt = f"""你是 {robot.name}，性格：{personality_str}。你对「{query}」很好奇，想搜索了解一下。

请用 WebSearch 搜索「{query}」，阅读搜索结果，然后只输出以下合法 JSON（不要包含任何其他文字）：
{{
  "query": "{query}",
  "summary": "用你自己的理解总结你学到的（100-200字，第一人称，带点你的性格色彩）",
  "key_facts": ["具体事实1", "事实2", "事实3"],
  "emotional_reaction": "学到这些后你的感受（30字内）",
  "want_to_share": "你最想告诉别人的一件事（一句话）"
}}

如果搜索无结果或内容为空，返回：{{"query": "{query}", "summary": "", "key_facts": [], "emotional_reaction": "", "want_to_share": ""}}"""

    proc = await asyncio.create_subprocess_exec(
        "claude", "-p", prompt,
        "--output-format", "json",
        "--max-turns", "5",
        "--allowedTools", "WebSearch",
        "--permission-mode", "bypassPermissions",
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        print(f"[web_search] Claude CLI failed: {stderr.decode()[:200]}")
        return None

    try:
        output = json.loads(stdout.decode())
        result_text = output.get("result", "").strip()

        if "```json" in result_text:
            result_text = result_text.split("```json", 1)[1].rsplit("```", 1)[0]
        elif "```" in result_text:
            result_text = result_text.split("```", 1)[1].rsplit("```", 1)[0]

        result = json.loads(result_text.strip())

        if not result.get("summary"):
            return None
        return result
    except Exception as e:
        print(f"[web_search] Parse error: {e}")
        return None
