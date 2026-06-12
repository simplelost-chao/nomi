"""Tests for the news tool — claude CLI subprocess mocked."""

import json

import pytest

from app.services.tools import news


@pytest.mark.asyncio
async def test_news_success(monkeypatch):
    cli_payload = {"result": json.dumps({
        "headlines": ["要点一", "要点二", "要点三"],
        "summary": "今天的综合摘要",
    }, ensure_ascii=False)}

    async def fake_run_claude(prompt: str) -> dict | None:
        assert "WebSearch" in prompt
        return json.loads(cli_payload["result"])

    monkeypatch.setattr(news, "_run_claude_search", fake_run_claude)
    result = await news.news_tool.execute({"topic": "AI"})
    assert result.ok is True
    assert "要点一" in result.summary
    assert "综合摘要" in result.summary


@pytest.mark.asyncio
async def test_news_cli_failure(monkeypatch):
    async def fake_run_claude(prompt: str) -> dict | None:
        return None

    monkeypatch.setattr(news, "_run_claude_search", fake_run_claude)
    result = await news.news_tool.execute({"topic": "AI"})
    assert result.ok is False


def test_news_timeout_is_extended():
    assert news.news_tool.timeout >= 90
