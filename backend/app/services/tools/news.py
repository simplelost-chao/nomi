"""News/hot-topics tool — reuses the claude CLI WebSearch subprocess pattern
(see app/services/web_search.py)."""

import asyncio
import json

from app.services.tools.base import Tool, ToolResult
from app.services.tools.registry import register


async def _run_claude_search(prompt: str) -> dict | None:
    """Run claude CLI with WebSearch and parse its JSON result. None on failure."""
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
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=90)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()  # 回收进程，避免僵尸
        return None
    if proc.returncode != 0:
        print(f"[tools.news] Claude CLI failed: {stderr.decode()[:200]}")
        return None
    try:
        output = json.loads(stdout.decode())
        result_text = output.get("result", "").strip()
        if "```json" in result_text:
            result_text = result_text.split("```json", 1)[1].rsplit("```", 1)[0]
        elif "```" in result_text:
            result_text = result_text.split("```", 1)[1].rsplit("```", 1)[0]
        return json.loads(result_text.strip())
    except Exception as e:
        print(f"[tools.news] Parse error: {e}")
        return None


async def _news_execute(params: dict) -> ToolResult:
    topic = (params.get("topic") or "").strip() or "今日热点新闻"
    prompt = f"""请用 WebSearch 搜索「{topic} 最新消息」，阅读结果后只输出以下合法 JSON（不要任何其他文字）：
{{
  "headlines": ["新闻要点1", "新闻要点2", "新闻要点3"],
  "summary": "100字以内的综合摘要"
}}
搜不到就返回 {{"headlines": [], "summary": ""}}"""
    result = await _run_claude_search(prompt)
    if not result or not result.get("summary"):
        return ToolResult(ok=False, error=f"没搜到「{topic}」的新闻")
    headlines = result.get("headlines") or []
    lines = [f"关于「{topic}」的最新消息：", result["summary"]]
    lines += [f"- {h}" for h in headlines[:3]]
    return ToolResult(ok=True, summary="\n".join(lines), data=result)


news_tool = register(Tool(
    name="news",
    display_name="新闻热点",
    description="搜索最新新闻和热点话题，返回要点和摘要",
    trigger_hints=["新闻", "热搜", "热点", "最近发生", "今天有什么事", "时事"],
    params_schema={"topic": "新闻主题关键词，用户没说就留空字符串（默认今日热点）"},
    execute=_news_execute,
    timeout=120,  # claude CLI 子进程慢，外层超时给足
))
