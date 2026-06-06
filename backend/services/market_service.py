"""
Market data via Yahoo Finance (free, unofficial chart endpoint).

IDX tickers map to Yahoo's ".JK" suffix (e.g. BBCA -> BBCA.JK); the IHSG index
is "^JKSE". A short in-memory TTL cache keeps us polite (no aggressive polling).

NOTE: this is an unofficial endpoint — shape may change. Failures raise and the
API layer returns 502; the frontend falls back to cached/mock values.
"""

import time
from datetime import datetime, timezone
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


def _parse_iso(at_iso: str) -> datetime:
    dt = datetime.fromisoformat(at_iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


async def _fetch_series(
    symbol: str, range_: str, interval: str
) -> List[Tuple[int, float]]:
    """Return [(unix_ts, close), ...] with nulls dropped, oldest first."""
    async with httpx.AsyncClient(timeout=10, headers=_UA) as client:
        resp = await client.get(
            YAHOO_CHART.format(symbol=symbol),
            params={"range": range_, "interval": interval},
        )
        resp.raise_for_status()
        payload = resp.json()
    results = (payload.get("chart") or {}).get("result") or []
    if not results:
        return []
    result = results[0]
    stamps = result.get("timestamp") or []
    try:
        closes = result["indicators"]["quote"][0]["close"]
    except (KeyError, IndexError, TypeError):
        return []
    return [(t, c) for t, c in zip(stamps, closes) if c is not None]


def _pick_range_interval(age_days: float) -> Tuple[str, str]:
    """Coarser granularity for older news (and longer Yahoo retention)."""
    if age_days <= 2:
        return "5d", "15m"
    if age_days <= 25:
        return "1mo", "60m"
    return "3mo", "1d"


def _reaction_from_series(
    series: List[Tuple[int, float]], at_ts: float, window_min: int
) -> dict:
    """Compute the post-news move from an already-fetched price series."""
    base = next(((t, c) for t, c in series if t >= at_ts), None)
    if base is None:
        return {"available": False, "reason": "no price data at/after the news time"}

    target_ts = base[0] + window_min * 60
    after = next(((t, c) for t, c in series if t >= target_ts), None)
    if after is None:
        after = series[-1]  # fall back to latest available bar
    used_window = max(1, round((after[0] - base[0]) / 60))

    base_price, after_price = base[1], after[1]
    pct = (after_price - base_price) / base_price * 100 if base_price else None

    return {
        "available": pct is not None,
        "basePrice": _round(base_price),
        "afterPrice": _round(after_price),
        "reactionPercent": _round(pct),
        "windowMinutes": used_window,
    }


async def fetch_reaction(
    ticker: str, at_iso: str, window_min: int = 60
) -> dict:
    """
    Measure how a ticker's price reacted in the window after a news timestamp.
    Granularity adapts to how old the news is. available=False when there isn't
    enough price history (e.g. news older than intraday retention).
    """
    at_ts = _parse_iso(at_iso).timestamp()
    age_days = (datetime.now(timezone.utc).timestamp() - at_ts) / 86400
    range_, interval = _pick_range_interval(age_days)
    series = await _fetch_series(to_yahoo_symbol(ticker), range_, interval)
    result = _reaction_from_series(series, at_ts, window_min)
    result["ticker"] = ticker.strip().upper()
    result["interval"] = interval
    return result


async def fetch_reactions(items: List[dict]) -> List[dict]:
    """
    Batched reaction lookup. Groups items by (symbol, range, interval) and
    fetches each unique series only ONCE — so a feed of 50 cards costs a handful
    of Yahoo calls, not 50. Each item may carry a "key" that's echoed back so the
    caller can map results to rows.
    """
    now_ts = datetime.now(timezone.utc).timestamp()

    # Parse every item up front; remember which group each belongs to.
    parsed: List[Optional[dict]] = []
    groups: Dict[Tuple[str, str, str], None] = {}
    for it in items:
        try:
            at_ts = _parse_iso(it["at"]).timestamp()
        except Exception:
            parsed.append(None)
            continue
        symbol = to_yahoo_symbol(it.get("ticker", ""))
        rng, iv = _pick_range_interval((now_ts - at_ts) / 86400)
        groups[(symbol, rng, iv)] = None
        parsed.append(
            {
                "key": it.get("key"),
                "ticker": (it.get("ticker") or "").strip().upper(),
                "symbol": symbol,
                "at_ts": at_ts,
                "window": int(it.get("window", 60)),
                "ri": (rng, iv),
            }
        )

    # Fetch each unique series once.
    series_by_group: Dict[Tuple[str, str, str], List[Tuple[int, float]]] = {}
    for key in groups:
        symbol, rng, iv = key
        try:
            series_by_group[key] = await _fetch_series(symbol, rng, iv)
        except Exception:
            series_by_group[key] = []

    # Build aligned results.
    results: List[dict] = []
    for raw, p in zip(items, parsed):
        if p is None:
            results.append(
                {"key": raw.get("key"), "available": False, "reason": "invalid item"}
            )
            continue
        rng, iv = p["ri"]
        series = series_by_group.get((p["symbol"], rng, iv), [])
        r = _reaction_from_series(series, p["at_ts"], p["window"])
        r["key"] = p["key"]
        r["ticker"] = p["ticker"]
        r["interval"] = iv
        results.append(r)
    return results
