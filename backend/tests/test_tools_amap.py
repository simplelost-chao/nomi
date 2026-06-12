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


POI_OK = {
    "status": "1",
    "pois": [
        {"name": "海底捞(王府井店)", "address": "王府井大街88号", "biz_ext": {"rating": "4.8"}},
        {"name": "小龙坎火锅", "address": "东直门内大街277号", "biz_ext": {"rating": "4.5"}},
    ],
}


@pytest.mark.asyncio
async def test_food_search_success(monkeypatch):
    async def fake_get(path, params):
        assert path == "/place/text"
        assert params["keywords"] == "火锅"
        assert params["city"] == "北京"
        assert params["types"] == "050000"
        return POI_OK

    monkeypatch.setattr(amap, "_amap_get", fake_get)
    result = await amap.food_search_tool.execute({"keyword": "火锅", "city": "北京"})
    assert result.ok is True
    assert "海底捞" in result.summary
    assert "4.8" in result.summary


@pytest.mark.asyncio
async def test_food_search_empty(monkeypatch):
    async def fake_get(path, params):
        return {"status": "1", "pois": []}

    monkeypatch.setattr(amap, "_amap_get", fake_get)
    result = await amap.food_search_tool.execute({"keyword": "火星菜", "city": "北京"})
    assert result.ok is False


@pytest.mark.asyncio
async def test_route_plan_success(monkeypatch):
    async def fake_get(path, params):
        if path == "/geocode/geo":
            return {"geocodes": [{"location": "116.40,39.90"}]}
        if path == "/direction/driving":
            return {"route": {"paths": [{"distance": "15000", "duration": "1800"}]}}
        raise AssertionError(path)

    monkeypatch.setattr(amap, "_amap_get", fake_get)
    result = await amap.route_plan_tool.execute(
        {"origin": "国贸", "destination": "西二旗", "city": "北京"}
    )
    assert result.ok is True
    assert "15.0 公里" in result.summary
    assert "30 分钟" in result.summary


@pytest.mark.asyncio
async def test_route_plan_geocode_fail(monkeypatch):
    async def fake_get(path, params):
        return {"geocodes": []}

    monkeypatch.setattr(amap, "_amap_get", fake_get)
    result = await amap.route_plan_tool.execute(
        {"origin": "不存在的地方", "destination": "西二旗", "city": "北京"}
    )
    assert result.ok is False


@pytest.mark.asyncio
async def test_route_plan_dest_geocode_fail(monkeypatch):
    call_count = {"n": 0}

    async def fake_get(path, params):
        if path == "/geocode/geo":
            call_count["n"] += 1
            if call_count["n"] == 1:
                return {"geocodes": [{"location": "116.40,39.90"}]}  # 起点成功
            return {"geocodes": []}  # 终点失败
        raise AssertionError(path)

    monkeypatch.setattr(amap, "_amap_get", fake_get)
    result = await amap.route_plan_tool.execute(
        {"origin": "国贸", "destination": "不存在的地方", "city": "北京"}
    )
    assert result.ok is False
    assert "不存在的地方" in result.error


@pytest.mark.asyncio
async def test_food_search_no_api_key(monkeypatch):
    monkeypatch.setattr("app.config.settings.amap_api_key", "")
    result = await amap.food_search_tool.execute({"keyword": "火锅"})
    assert result.ok is False
    assert "Key" in result.error


@pytest.mark.asyncio
async def test_route_plan_no_api_key(monkeypatch):
    monkeypatch.setattr("app.config.settings.amap_api_key", "")
    result = await amap.route_plan_tool.execute({"origin": "a", "destination": "b"})
    assert result.ok is False
    assert "Key" in result.error
