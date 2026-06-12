"""Tests for amap tools — HTTP layer mocked via monkeypatch on _amap_get."""

import pytest

from app.services.tools import amap


@pytest.fixture(autouse=True)
def fake_key(monkeypatch):
    monkeypatch.setattr("app.config.settings.amap_api_key", "test-key")
    monkeypatch.setattr("app.config.settings.default_city", "北京")


WEATHER_OK = {
    "status": "1",
    "forecasts": [{
        "city": "北京市",
        "casts": [
            {"date": "2026-06-12", "dayweather": "晴", "daytemp": "30", "nighttemp": "18",
             "daywind": "南", "daypower": "≤3"},
            {"date": "2026-06-13", "dayweather": "多云", "daytemp": "28", "nighttemp": "17",
             "daywind": "南", "daypower": "≤3"},
        ],
    }],
}


@pytest.mark.asyncio
async def test_weather_success(monkeypatch):
    async def fake_get(path, params):
        assert path == "/weather/weatherInfo"
        assert params["city"] == "北京"
        return WEATHER_OK

    monkeypatch.setattr(amap, "_amap_get", fake_get)
    result = await amap.weather_tool.execute({"city": "北京"})
    assert result.ok is True
    assert "北京市" in result.summary
    assert "晴" in result.summary


@pytest.mark.asyncio
async def test_weather_uses_default_city(monkeypatch):
    seen = {}

    async def fake_get(path, params):
        seen["city"] = params["city"]
        return WEATHER_OK

    monkeypatch.setattr(amap, "_amap_get", fake_get)
    result = await amap.weather_tool.execute({"city": ""})
    assert seen["city"] == "北京"
    assert result.ok is True


@pytest.mark.asyncio
async def test_weather_city_not_found(monkeypatch):
    async def fake_get(path, params):
        if path == "/weather/weatherInfo":
            return {"status": "1", "forecasts": []}
        if path == "/config/district":
            return {"districts": []}
        raise AssertionError(path)

    monkeypatch.setattr(amap, "_amap_get", fake_get)
    result = await amap.weather_tool.execute({"city": "不存在的城市"})
    assert result.ok is False
    assert result.error


@pytest.mark.asyncio
async def test_weather_no_api_key(monkeypatch):
    monkeypatch.setattr("app.config.settings.amap_api_key", "")
    result = await amap.weather_tool.execute({"city": "北京"})
    assert result.ok is False
    assert "Key" in result.error


@pytest.mark.asyncio
async def test_weather_amap_business_error(monkeypatch):
    """amap 业务错误（HTTP 200 + status=0）应给出真实错误，而不是"找不到城市"。"""

    async def fake_get(path, params):
        raise RuntimeError("amap error 10001: INVALID_USER_KEY")

    monkeypatch.setattr(amap, "_amap_get", fake_get)
    result = await amap.weather_tool.execute({"city": "北京"})
    assert result.ok is False
    assert "INVALID_USER_KEY" in result.error
