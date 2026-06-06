"""
Market data via Yahoo Finance (free, unofficial chart endpoint).

IDX tickers map to Yahoo's ".JK" suffix (e.g. BBCA -> BBCA.JK); the IHSG index
is "^JKSE". A short in-memory TTL cache keeps us polite (no aggressive polling).

NOTE: this is an unofficial endpoint — shape may change. Failures raise and the
API layer returns 502; the frontend falls back to cached/mock values.
"""

import time
from typing import Dict, List, Optional, Tuple

import httpx

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
IHSG_SYMBOL = "^JKSE"

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
_CACHE_TTL_SEC = 60
_cache: Dict[str, Tuple[float, dict]] = {}

# UI time-range -> (Yahoo range, interval)
RANGE_INTERVAL: Dict[str, Tuple[str, str]] = {
    "1H": ("1d", "2m"),
    "1D": ("1d", "5m"),
    "1W": ("5d", "30m"),
    "1M": ("1mo", "1d"),
    "1Y": ("1y", "1wk"),
}


def to_yahoo_symbol(ticker: str) -> str:
    t = ticker.strip().upper()
    if t.startswith("^") or "." in t:
        return t
    return f"{t}.JK"


def _round(v: Optional[float], n: int = 2) -> Optional[float]:
    return round(v, n) if isinstance(v, (int, float)) else None


async def fetch_quote(
    ticker: str, range_: str = "1d", interval: str = "1d"
) -> dict:
    # range="1d" makes chartPreviousClose the prior trading day's close, so
    # change/changePercent are a true day-over-day move. Wider ranges (passed by
    # the chart endpoint) are only used for sparkline points, not the change.
    symbol = to_yahoo_symbol(ticker)
    cache_key = f"{symbol}:{range_}:{interval}"
    hit = _cache.get(cache_key)
    if hit and (time.time() - hit[0]) < _CACHE_TTL_SEC:
        return hit[1]

    async with httpx.AsyncClient(timeout=10, headers=_UA) as client:
        resp = await client.get(
            YAHOO_CHART.format(symbol=symbol),
            params={"range": range_, "interval": interval},
        )
        resp.raise_for_status()
        payload = resp.json()

    results = (payload.get("chart") or {}).get("result") or []
    if not results:
        raise ValueError(f"No market data for {symbol}")
    result = results[0]
    meta = result.get("meta", {})

    price = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")

    closes: List[float] = []
    try:
        raw = result["indicators"]["quote"][0]["close"]
        closes = [c for c in raw if c is not None]
    except (KeyError, IndexError, TypeError):
        closes = []

    change = (price - prev) if price is not None and prev is not None else None
    change_pct = (change / prev * 100) if change is not None and prev else None

    quote = {
        "ticker": ticker.strip().upper(),
        "symbol": symbol,
        "price": _round(price),
        "previousClose": _round(prev),
        "change": _round(change),
        "changePercent": _round(change_pct),
        "currency": meta.get("currency"),
        "marketState": meta.get("marketState"),
        "sparkline": [_round(c) for c in closes],
    }
    _cache[cache_key] = (time.time(), quote)
    return quote
