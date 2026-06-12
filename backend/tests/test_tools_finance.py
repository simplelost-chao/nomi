"""Tests for finance tools — HTTP helpers mocked."""

import pytest

from app.services.tools import finance


@pytest.mark.asyncio
async def test_stock_success(monkeypatch):
    sina_text = 'var hq_str_sh600519="贵州茅台,1700.00,1690.00,1710.50,1720.00,1695.00";'

    async def fake_fetch(symbol: str) -> str:
        assert symbol == "sh600519"
        return sina_text

    monkeypatch.setattr(finance, "_fetch_sina", fake_fetch)
    result = await finance.stock_tool.execute({"symbol": "sh600519"})
    assert result.ok is True
    assert "贵州茅台" in result.summary
    assert "1710.50" in result.summary
    assert "涨" in result.summary  # 1710.50 > 1690.00


@pytest.mark.asyncio
async def test_stock_not_found(monkeypatch):
    async def fake_fetch(symbol: str) -> str:
        return 'var hq_str_sh999999="";'

    monkeypatch.setattr(finance, "_fetch_sina", fake_fetch)
    result = await finance.stock_tool.execute({"symbol": "sh999999"})
    assert result.ok is False


@pytest.mark.asyncio
async def test_stock_missing_symbol():
    result = await finance.stock_tool.execute({})
    assert result.ok is False


@pytest.mark.asyncio
async def test_crypto_success(monkeypatch):
    async def fake_get_json(url: str, params: dict | None = None) -> dict:
        return {"bitcoin": {"usd": 120000, "cny": 860000, "usd_24h_change": 2.5}}

    monkeypatch.setattr(finance, "_get_json", fake_get_json)
    result = await finance.crypto_tool.execute({"coin": "bitcoin"})
    assert result.ok is True
    assert "bitcoin" in result.summary
    assert "涨" in result.summary


@pytest.mark.asyncio
async def test_crypto_unknown_coin(monkeypatch):
    async def fake_get_json(url: str, params: dict | None = None) -> dict:
        return {}

    monkeypatch.setattr(finance, "_get_json", fake_get_json)
    result = await finance.crypto_tool.execute({"coin": "notacoin"})
    assert result.ok is False


@pytest.mark.asyncio
async def test_forex_success(monkeypatch):
    async def fake_get_json(url: str, params: dict | None = None) -> dict:
        assert url.endswith("/USD")
        return {"result": "success", "rates": {"CNY": 7.1234}}

    monkeypatch.setattr(finance, "_get_json", fake_get_json)
    result = await finance.forex_tool.execute({"base": "USD", "target": "CNY"})
    assert result.ok is True
    assert "7.1234" in result.summary
