"""
IHSG daily market prospect engine.

Builds a market overview for the Jakarta Composite (^JKSE): technical state,
the macro catalysts that drive it, and a plain-language prospect summary.

## Two honest limitations, stated up front

**Net foreign flow (bandarmologi) is NOT included.** There is no free source
for aggregate IDX foreign net buy/sell. IDX's own endpoints sit behind
Cloudflare and answer 403 to any non-browser client (verified: both
`TradingSummary/GetStockSummary` and the announcements API). Driving a headless
browser through that challenge would be evading a stated access control, so the
field is reported as unavailable with a reason rather than filled with a
plausible-looking number. Foreign flow is precisely the kind of figure retail
investors act on, and a fabricated one is worse than a missing one.

**The prospect summary is rule-based, not LLM-generated.** No inference backend
is configured on this project — no Groq key, no Ollama listening, and the
Anthropic key is intentionally empty. Rather than fail or silently emit
nothing, the synthesis is deterministic: every sentence traces to a threshold
you can point at. `synthesise_prospect()` is isolated so a Groq/Ollama call can
replace it later without touching data collection.
"""

import asyncio
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

INDEX_SYMBOL = "^JKSE"

# Macro catalysts. Coal has no free Yahoo futures contract (verified — every
# documented symbol returns empty), so it is absent rather than proxied here;
# the commodity tracker carries miner proxies for that, clearly labelled.
_CATALYSTS: List[Dict[str, str]] = [
    {"symbol": "USDIDR=X", "name": "USD/IDR", "kind": "fx"},
    {"symbol": "GC=F", "name": "Emas", "kind": "commodity"},
    {"symbol": "CL=F", "name": "Minyak WTI", "kind": "commodity"},
    {"symbol": "BZ=F", "name": "Minyak Brent", "kind": "commodity"},
    {"symbol": "HG=F", "name": "Tembaga", "kind": "commodity"},
    {"symbol": "^TNX", "name": "US Treasury 10Y", "kind": "rates"},
]

_TTL_SEC = 600  # overview is a daily view; 10 min is plenty
_cache: Dict[str, Any] = {"at": 0.0, "value": None}

# RSI bands and the trend rules the prospect text is derived from.
_RSI_OVERBOUGHT = 70
_RSI_OVERSOLD = 30


@dataclass
class IHSGOverview:
    as_of: str
    last_close: float
    change: Optional[float]
    change_percent: Optional[float]

    # Technicals
    ema20: Optional[float]
    ema50: Optional[float]
    ema200: Optional[float]
    rsi: Optional[float]
    macd: Optional[float]
    macd_signal: Optional[float]
    macd_histogram: Optional[float]
    ihsg_support: Optional[float]
    ihsg_resistance: Optional[float]

    # Synthesis
    ihsg_status: str  # "BULLISH" | "BEARISH" | "SIDEWAYS / CONSOLIDATION"
    market_prospect_summary: str
    drivers: List[str] = field(default_factory=list)

    # Macro
    catalysts: List[Dict[str, Any]] = field(default_factory=list)

    # Foreign flow — see module docstring on why this is not populated.
    foreign_flow_available: bool = False
    foreign_flow_summary: Optional[str] = None
    foreign_flow_reason: Optional[str] = None

    warnings: List[str] = field(default_factory=list)
    disclaimer: str = (
        "Ringkasan teknikal otomatis — bukan rekomendasi jual/beli. "
        "Dihitung dari data harga historis dan dapat berubah."
    )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── Data collection ──────────────────────────────────────────────────────────


def _fetch_index_blocking() -> Any:
    """Daily ^JKSE history. Blocking — call via asyncio.to_thread."""
    import yfinance as yf

    df = yf.Ticker(INDEX_SYMBOL).history(period="2y", interval="1d")
    if df is None or df.empty:
        raise ValueError(f"no data for {INDEX_SYMBOL}")
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    if getattr(df.index, "tz", None) is not None:
        df.index = df.index.tz_localize(None)
    return df


def _zone_summary(zone: Any) -> Optional[Dict[str, Any]]:
    """Compact zone payload for the IHSG report — band, strength, evidence."""
    if zone is None:
        return None
    return {
        "low": round(zone.low, 2),
        "high": round(zone.high, 2),
        "label": zone.label,
        "strength": zone.strength,
        "evidence": zone.evidence(),
    }


def _compute_technicals(df: Any) -> Dict[str, Any]:
    """EMA20/50/200, RSI14, MACD and nearest S/R for the index."""
    import numpy as np
    from ta.momentum import RSIIndicator
    from ta.trend import EMAIndicator, MACD
    from ta.volatility import AverageTrueRange

    # Zones, not the old single-price levels: the index report and /chart must
    # not disagree about where support is for the same symbol.
    from ta_engine.support_resistance import build_zones, nearest_zones

    close, high, low = df["Close"], df["High"], df["Low"]

    def _last(series: Any) -> Optional[float]:
        try:
            v = float(series.iloc[-1])
            return v if np.isfinite(v) else None
        except Exception:
            return None

    ema20 = _last(EMAIndicator(close, window=20).ema_indicator())
    ema50 = _last(EMAIndicator(close, window=50).ema_indicator())
    # EMA200 needs 200 bars; a 2y pull gives ~490 so this is defined in practice,
    # but stay tolerant rather than raising on a short history.
    ema200 = _last(EMAIndicator(close, window=200).ema_indicator()) if len(df) >= 200 else None
    rsi = _last(RSIIndicator(close, window=14).rsi())

    macd_ind = MACD(close)
    macd = _last(macd_ind.macd())
    macd_signal = _last(macd_ind.macd_signal())
    macd_hist = _last(macd_ind.macd_diff())

    atr_series = AverageTrueRange(high, low, close, window=14).average_true_range()
    atr = _last(atr_series) or 0.0

    support = resistance = None
    support_zone = resistance_zone = None
    if atr > 0:
        entry = float(close.iloc[-1])
        sup, res = nearest_zones(entry, build_zones(df, atr, entry))
        # Headline numbers report the edge price meets first — the TOP of a
        # support band, the BOTTOM of a resistance band.
        support = round(sup.high, 2) if sup else None
        resistance = round(res.low, 2) if res else None
        support_zone = _zone_summary(sup)
        resistance_zone = _zone_summary(res)

    last_close = float(close.iloc[-1])
    prev_close = float(close.iloc[-2]) if len(close) > 1 else None
    change = round(last_close - prev_close, 2) if prev_close else None
    change_pct = (
        round((last_close - prev_close) / prev_close * 100, 2) if prev_close else None
    )

    return {
        "last_close": round(last_close, 2),
        "change": change,
        "change_percent": change_pct,
        "ema20": round(ema20, 2) if ema20 else None,
        "ema50": round(ema50, 2) if ema50 else None,
        "ema200": round(ema200, 2) if ema200 else None,
        "rsi": round(rsi, 2) if rsi else None,
        "macd": round(macd, 4) if macd else None,
        "macd_signal": round(macd_signal, 4) if macd_signal else None,
        "macd_histogram": round(macd_hist, 4) if macd_hist else None,
        "support": support,
        "resistance": resistance,
        "support_zone": support_zone,
        "resistance_zone": resistance_zone,
        "as_of": df.index[-1].strftime("%Y-%m-%d"),
    }


def _fetch_catalysts_blocking() -> List[Dict[str, Any]]:
    """Daily change for each macro catalyst. Blocking — run in a thread."""
    import yfinance as yf

    symbols = [c["symbol"] for c in _CATALYSTS]
    out: List[Dict[str, Any]] = []
    try:
        tickers = yf.Tickers(" ".join(symbols))
    except Exception as exc:
        logger.warning("ihsg.catalysts_failed error=%s", exc)
        return out

    for meta in _CATALYSTS:
        try:
            info = tickers.tickers[meta["symbol"]].fast_info
            price = info.get("lastPrice") if hasattr(info, "get") else info.last_price
            prev = info.get("previousClose") if hasattr(info, "get") else info.previous_close
            if price is None:
                continue
            price = float(price)
            prev_f = float(prev) if prev else None
            pct = round((price - prev_f) / prev_f * 100, 2) if prev_f else None
            out.append({
                "symbol": meta["symbol"],
                "name": meta["name"],
                "kind": meta["kind"],
                "price": round(price, 4),
                "changePercent": pct,
            })
        except Exception as exc:
            logger.debug("ihsg.catalyst_skipped symbol=%s error=%s", meta["symbol"], exc)
    return out


# ── Synthesis (deterministic; swap for an LLM call when one is configured) ───


def _classify_status(t: Dict[str, Any]) -> str:
    """
    Trend label from EMA stack + price position.

    Bullish needs price above EMA20 with EMA20 above EMA50; bearish is the
    mirror. Anything mixed is consolidation — most days are, and saying so is
    more useful than forcing a direction.
    """
    close, e20, e50 = t["last_close"], t["ema20"], t["ema50"]
    if e20 is None or e50 is None:
        return "SIDEWAYS / CONSOLIDATION"
    if close > e20 and e20 > e50:
        return "BULLISH"
    if close < e20 and e20 < e50:
        return "BEARISH"
    return "SIDEWAYS / CONSOLIDATION"


def synthesise_prospect(
    tech: Dict[str, Any], catalysts: List[Dict[str, Any]], status: str
) -> Dict[str, Any]:
    """
    Build the prospect paragraph and its driver list.

    Deterministic by design — see the module docstring. Each sentence maps to a
    stated threshold, so any claim in the output can be traced to the number
    that produced it.
    """
    drivers: List[str] = []
    parts: List[str] = []

    chg = tech.get("change_percent")
    if chg is not None:
        direction = "menguat" if chg >= 0 else "melemah"
        parts.append(
            f"IHSG ditutup di {tech['last_close']:,.2f} ({direction} {abs(chg):.2f}%)."
        )

    # Trend structure
    if status == "BULLISH":
        parts.append(
            "Struktur tren jangka pendek masih naik — harga bertahan di atas EMA20 "
            "dan EMA20 di atas EMA50."
        )
        drivers.append("Struktur EMA mendukung tren naik")
    elif status == "BEARISH":
        parts.append(
            "Struktur tren jangka pendek menurun — harga di bawah EMA20 dan "
            "EMA20 di bawah EMA50."
        )
        drivers.append("Struktur EMA menekan ke bawah")
    else:
        parts.append(
            "Struktur EMA belum searah, indeks cenderung bergerak menyamping "
            "(konsolidasi)."
        )
        drivers.append("EMA belum searah — konsolidasi")

    # Long-term context
    e200 = tech.get("ema200")
    if e200:
        above = tech["last_close"] > e200
        parts.append(
            f"Terhadap EMA200 ({e200:,.2f}) indeks berada di "
            f"{'atas' if above else 'bawah'}nya, menandakan bias jangka panjang masih "
            f"{'positif' if above else 'negatif'}."
        )
        drivers.append(
            f"{'Di atas' if above else 'Di bawah'} EMA200 (bias jangka panjang)"
        )

    # Momentum
    rsi = tech.get("rsi")
    if rsi is not None:
        if rsi >= _RSI_OVERBOUGHT:
            parts.append(f"RSI {rsi:.0f} sudah di area jenuh beli — rawan koreksi teknikal.")
            drivers.append(f"RSI {rsi:.0f} overbought")
        elif rsi <= _RSI_OVERSOLD:
            parts.append(f"RSI {rsi:.0f} di area jenuh jual — peluang rebound teknikal.")
            drivers.append(f"RSI {rsi:.0f} oversold")
        else:
            drivers.append(f"RSI {rsi:.0f} netral")

    hist = tech.get("macd_histogram")
    if hist is not None:
        drivers.append(
            f"MACD histogram {'positif' if hist >= 0 else 'negatif'} ({hist:+.2f})"
        )

    # Levels. Reported as bands with a strength word, matching /chart — a single
    # number implies a precision the structure does not have.
    def _band(zone: Optional[Dict[str, Any]], fallback: Optional[float]) -> Optional[str]:
        if zone:
            return f"{zone['low']:,.0f}–{zone['high']:,.0f} ({zone['label']})"
        return f"{fallback:,.0f}" if fallback else None

    sup = _band(tech.get("support_zone"), tech.get("support"))
    res = _band(tech.get("resistance_zone"), tech.get("resistance"))
    if sup and res:
        parts.append(f"Level kunci: support {sup}, resistance {res}.")
    elif sup:
        parts.append(f"Support terdekat {sup}; resistance belum terbentuk di atas harga.")
    elif res:
        parts.append(f"Resistance terdekat {res}; support belum terbentuk di bawah harga.")

    # Macro colour — only the movers, so the paragraph stays short.
    movers = [c for c in catalysts if c.get("changePercent") is not None
              and abs(c["changePercent"]) >= 1.0]
    if movers:
        movers.sort(key=lambda c: -abs(c["changePercent"]))
        top = movers[:2]
        desc = ", ".join(
            f"{c['name']} {c['changePercent']:+.2f}%" for c in top
        )
        parts.append(f"Katalis makro yang bergerak signifikan: {desc}.")
        for c in top:
            drivers.append(f"{c['name']} {c['changePercent']:+.2f}%")

    fx = next((c for c in catalysts if c["symbol"] == "USDIDR=X"), None)
    if fx and fx.get("changePercent") is not None:
        weaker = fx["changePercent"] > 0  # USD/IDR up = rupiah weaker
        parts.append(
            f"Rupiah {'melemah' if weaker else 'menguat'} ke {fx['price']:,.0f}/USD, "
            f"{'menambah tekanan pada' if weaker else 'memberi ruang bagi'} aliran dana asing."
        )

    return {"summary": " ".join(parts), "drivers": drivers}


# ── Public entry point ───────────────────────────────────────────────────────


async def build_ihsg_overview(force: bool = False) -> IHSGOverview:
    """
    Assemble the daily IHSG overview. Cached for `_TTL_SEC`.

    yfinance calls are blocking, so both the index history and the catalyst
    batch run in worker threads — this is invoked from a FastAPI handler and
    must not stall the event loop or the SSE broadcast.
    """
    if not force:
        hit = _cache.get("value")
        if hit is not None and (time.time() - _cache["at"]) < _TTL_SEC:
            return hit

    started = time.perf_counter()
    df = await asyncio.to_thread(_fetch_index_blocking)
    tech = await asyncio.to_thread(_compute_technicals, df)
    catalysts = await asyncio.to_thread(_fetch_catalysts_blocking)

    status = _classify_status(tech)
    prospect = synthesise_prospect(tech, catalysts, status)

    warnings: List[str] = []
    if tech.get("ema200") is None:
        warnings.append("EMA200 tidak tersedia — riwayat harga kurang dari 200 bar.")
    if not catalysts:
        warnings.append("Data katalis makro gagal diambil untuk siklus ini.")

    overview = IHSGOverview(
        as_of=tech["as_of"],
        last_close=tech["last_close"],
        change=tech["change"],
        change_percent=tech["change_percent"],
        ema20=tech["ema20"],
        ema50=tech["ema50"],
        ema200=tech["ema200"],
        rsi=tech["rsi"],
        macd=tech["macd"],
        macd_signal=tech["macd_signal"],
        macd_histogram=tech["macd_histogram"],
        ihsg_support=tech["support"],
        ihsg_resistance=tech["resistance"],
        ihsg_status=status,
        market_prospect_summary=prospect["summary"],
        drivers=prospect["drivers"],
        catalysts=catalysts,
        foreign_flow_available=False,
        foreign_flow_summary=None,
        foreign_flow_reason=(
            "Aggregate IDX foreign net buy/sell is not available from any free "
            "source — idx.co.id sits behind a Cloudflare challenge and returns "
            "403 to non-browser clients. Reported as unavailable rather than "
            "estimated, because a fabricated flow figure would be acted on."
        ),
        warnings=warnings,
    )

    _cache["value"] = overview
    _cache["at"] = time.time()
    logger.info(
        "ihsg.overview_built close=%.2f status=%s rsi=%s catalysts=%d elapsed=%.2fs",
        overview.last_close, status, overview.rsi, len(catalysts),
        time.perf_counter() - started,
    )
    return overview
