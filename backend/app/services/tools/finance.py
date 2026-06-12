"""Finance tools: A-share quotes (Sina), crypto (CoinGecko), forex (open.er-api.com).
All free endpoints, no API key required."""

import httpx

from app.services.tools.base import Tool, ToolResult
from app.services.tools.registry import register


async def _get_json(url: str, params: dict | None = None) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


async def _fetch_sina(symbol: str) -> str:
    # hq.sinajs.cn 要求 Referer，返回 GB18030 编码文本
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"https://hq.sinajs.cn/list={symbol}",
            headers={"Referer": "https://finance.sina.com.cn"},
        )
        resp.raise_for_status()
        return resp.content.decode("gb18030", errors="replace")


async def _stock_execute(params: dict) -> ToolResult:
    symbol = (params.get("symbol") or "").strip().lower()
    if not symbol:
        return ToolResult(ok=False, error="缺少股票代码")
    try:
        text = await _fetch_sina(symbol)
        payload = text.split('"')[1] if '"' in text else ""
        fields = payload.split(",")
        if len(fields) < 4 or not fields[0]:
            return ToolResult(ok=False, error=f"没查到「{symbol}」的行情")
        name, open_, prev_close, current = fields[0], fields[1], fields[2], fields[3]
        prev = float(prev_close)
        change = (float(current) - prev) / prev * 100 if prev else 0.0
        direction = "涨" if change >= 0 else "跌"
        summary = (
            f"{name}（{symbol}）现价 {current} 元，今开 {open_}，"
            f"较昨收{direction} {abs(change):.2f}%"
        )
        return ToolResult(ok=True, summary=summary,
                          data={"name": name, "current": current, "change_pct": change})
    except Exception as e:
        return ToolResult(ok=False, error=f"股票查询失败：{e}")


stock_tool = register(Tool(
    name="stock_quote",
    display_name="股票行情",
    description="查询A股/港股/美股实时行情。A股代码如 sh600519、sz000001，美股如 gb_aapl",
    trigger_hints=["股票", "股价", "大盘", "茅台", "上证", "涨了", "跌了"],
    params_schema={"symbol": "股票代码：沪市 sh+6位、深市 sz+6位、美股 gb_+小写代码；尽量从用户说的公司名推断代码"},
    execute=_stock_execute,
))


async def _crypto_execute(params: dict) -> ToolResult:
    coin = (params.get("coin") or "").strip().lower() or "bitcoin"
    try:
        data = await _get_json(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": coin, "vs_currencies": "usd,cny", "include_24hr_change": "true"},
        )
        if coin not in data:
            return ToolResult(ok=False, error=f"没查到币种「{coin}」")
        q = data[coin]
        change = q.get("usd_24h_change") or 0.0
        direction = "涨" if change >= 0 else "跌"
        summary = (
            f"{coin} 现价 ${q.get('usd'):,}（约 ¥{q.get('cny'):,}），"
            f"24小时{direction} {abs(change):.1f}%"
        )
        return ToolResult(ok=True, summary=summary, data=q)
    except Exception as e:
        return ToolResult(ok=False, error=f"币价查询失败：{e}")


crypto_tool = register(Tool(
    name="crypto_price",
    display_name="加密货币行情",
    description="查询加密货币价格，coin 用 CoinGecko 的 id，如 bitcoin、ethereum、dogecoin",
    trigger_hints=["比特币", "以太坊", "币价", "BTC", "ETH", "加密货币", "狗狗币"],
    params_schema={"coin": "币种 id（英文小写），如 bitcoin、ethereum；从用户说的币名推断"},
    execute=_crypto_execute,
))


async def _forex_execute(params: dict) -> ToolResult:
    base = (params.get("base") or "").strip().upper() or "USD"
    target = (params.get("target") or "").strip().upper() or "CNY"
    try:
        data = await _get_json(f"https://open.er-api.com/v6/latest/{base}")
        rate = (data.get("rates") or {}).get(target)
        if not rate:
            return ToolResult(ok=False, error=f"没查到 {base}/{target} 的汇率")
        summary = f"当前汇率：1 {base} ≈ {rate:.4f} {target}"
        return ToolResult(ok=True, summary=summary, data={"base": base, "target": target, "rate": rate})
    except Exception as e:
        return ToolResult(ok=False, error=f"汇率查询失败：{e}")


forex_tool = register(Tool(
    name="exchange_rate",
    display_name="汇率查询",
    description="查询两种货币之间的汇率，货币用三位代码如 USD、CNY、JPY、EUR",
    trigger_hints=["汇率", "美元", "日元", "欧元", "换多少", "兑换"],
    params_schema={"base": "源货币三位代码，默认 USD", "target": "目标货币三位代码，默认 CNY"},
    execute=_forex_execute,
))
