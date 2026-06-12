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


async def _food_search_execute(params: dict) -> ToolResult:
    if not settings.amap_api_key:
        return ToolResult(ok=False, error="未配置高德 API Key（NOMI_AMAP_API_KEY）")
    keyword = (params.get("keyword") or "").strip() or "美食"
    city = (params.get("city") or "").strip() or settings.default_city
    try:
        data = await _amap_get("/place/text", {
            "keywords": keyword,
            "city": city,
            "types": "050000",  # 餐饮服务大类
            "offset": 5,
            "page": 1,
            "extensions": "all",
        })
        pois = data.get("pois") or []
        if not pois:
            return ToolResult(ok=False, error=f"在{city}没找到「{keyword}」相关的店")
        lines = [f"在{city}找到这些「{keyword}」相关的店："]
        for p in pois[:5]:
            rating = (p.get("biz_ext") or {}).get("rating") or "暂无评分"
            lines.append(f"- {p.get('name')}（{p.get('address')}，评分 {rating}）")
        return ToolResult(ok=True, summary="\n".join(lines), data={"pois": pois[:5]})
    except Exception as e:
        return ToolResult(ok=False, error=f"美食搜索失败：{e}")


food_search_tool = register(Tool(
    name="food_search",
    display_name="美食搜索",
    description="搜索某个城市的餐厅、美食、小吃等餐饮场所，返回店名、地址和评分",
    trigger_hints=["好吃的", "餐厅", "美食", "吃什么", "饭店", "火锅", "外卖", "小吃", "附近有什么吃"],
    params_schema={
        "keyword": "美食关键词，如「火锅」「日料」「烤鸭」",
        "city": "城市名，用户没提地点就留空字符串",
    },
    execute=_food_search_execute,
))


async def _route_plan_execute(params: dict) -> ToolResult:
    if not settings.amap_api_key:
        return ToolResult(ok=False, error="未配置高德 API Key（NOMI_AMAP_API_KEY）")
    origin_addr = (params.get("origin") or "").strip()
    dest_addr = (params.get("destination") or "").strip()
    city = (params.get("city") or "").strip() or settings.default_city
    if not origin_addr or not dest_addr:
        return ToolResult(ok=False, error="路线规划需要起点和终点")
    try:
        async def geocode(address: str) -> str | None:
            data = await _amap_get("/geocode/geo", {"address": address, "city": city})
            geocodes = data.get("geocodes") or []
            return geocodes[0].get("location") if geocodes else None

        origin = await geocode(origin_addr)
        if not origin:
            return ToolResult(ok=False, error=f"找不到地点「{origin_addr}」")
        dest = await geocode(dest_addr)
        if not dest:
            return ToolResult(ok=False, error=f"找不到地点「{dest_addr}」")

        data = await _amap_get("/direction/driving", {"origin": origin, "destination": dest})
        paths = (data.get("route") or {}).get("paths") or []
        if not paths:
            return ToolResult(ok=False, error="没规划出路线")
        path = paths[0]
        distance_km = int(path.get("distance", 0)) / 1000
        duration_min = int(path.get("duration", 0)) // 60
        summary = (
            f"从{origin_addr}开车到{dest_addr}约 {distance_km:.1f} 公里，"
            f"预计 {duration_min} 分钟。"
        )
        return ToolResult(ok=True, summary=summary,
                          data={"distance_km": distance_km, "duration_min": duration_min})
    except Exception as e:
        return ToolResult(ok=False, error=f"路线规划失败：{e}")


route_plan_tool = register(Tool(
    name="route_plan",
    display_name="路线规划",
    description="规划两地之间的驾车路线，返回距离和预计耗时",
    trigger_hints=["怎么走", "路线", "怎么去", "多远", "导航", "开车去", "要多久"],
    params_schema={
        "origin": "起点地名",
        "destination": "终点地名",
        "city": "城市名，用户没提就留空字符串",
    },
    execute=_route_plan_execute,
))
