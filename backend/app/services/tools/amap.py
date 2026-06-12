"""Amap (高德) tools: weather / food_search / route_plan — one free API key covers all."""

import httpx

from app.config import settings
from app.services.tools.base import Tool, ToolResult
from app.services.tools.registry import register

_AMAP_BASE = "https://restapi.amap.com/v3"


async def _amap_get(path: str, params: dict) -> dict:
    params = {**params, "key": settings.amap_api_key}
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{_AMAP_BASE}{path}", params=params)
        resp.raise_for_status()
        data = resp.json()
        # 高德业务错误返回 HTTP 200 + status=0（如无效 Key、配额耗尽），必须显式抛出
        if data.get("status") == "0":
            raise RuntimeError(f"amap error {data.get('infocode')}: {data.get('info')}")
        return data


async def _resolve_adcode(city: str) -> str | None:
    data = await _amap_get("/config/district", {"keywords": city, "subdistrict": 0})
    districts = data.get("districts") or []
    return districts[0].get("adcode") if districts else None


async def _weather_execute(params: dict) -> ToolResult:
    if not settings.amap_api_key:
        return ToolResult(ok=False, error="未配置高德 API Key（NOMI_AMAP_API_KEY）")
    city = (params.get("city") or "").strip() or settings.default_city
    try:
        data = await _amap_get("/weather/weatherInfo", {"city": city, "extensions": "all"})
        forecasts = data.get("forecasts") or []
        if not forecasts:
            # 城市名不被天气接口识别时，先解析 adcode 再查一次
            adcode = await _resolve_adcode(city)
            if not adcode:
                return ToolResult(ok=False, error=f"找不到城市「{city}」")
            data = await _amap_get("/weather/weatherInfo", {"city": adcode, "extensions": "all"})
            forecasts = data.get("forecasts") or []
            if not forecasts:
                return ToolResult(ok=False, error=f"查不到「{city}」的天气")
        forecast = forecasts[0]
        casts = forecast.get("casts") or []
        if not casts:
            return ToolResult(ok=False, error="天气数据为空")
        lines = [f"{forecast.get('city', city)}未来天气："]
        for c in casts[:3]:
            lines.append(
                f"{c.get('date')}：白天{c.get('dayweather')}，"
                f"{c.get('nighttemp')}~{c.get('daytemp')}°C，"
                f"{c.get('daywind')}风{c.get('daypower')}级"
            )
        return ToolResult(ok=True, summary="\n".join(lines), data=forecast)
    except Exception as e:
        return ToolResult(ok=False, error=f"天气查询失败：{e}")


weather_tool = register(Tool(
    name="weather",
    display_name="天气查询",
    description="查询中国城市的当天和未来三天天气预报",
    trigger_hints=["天气", "下雨", "下雪", "降温", "气温", "温度", "台风", "雾霾"],
    params_schema={"city": "城市名，用户没提地点就留空字符串"},
    execute=_weather_execute,
))
