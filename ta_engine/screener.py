"""
Rule-based technical screener.

Ranks a universe of IDX tickers by a transparent, deterministic score built from
the same indicators `chart_generator` uses. This is explicitly **not** an AI
model: ANTHROPIC_API_KEY is empty by design on this project, and a made-up
"conviction score" from an LLM would be less trustworthy than arithmetic you can
audit. Every point in the score traces to a named rule below.

Screening is a filter, not a recommendation — output carries the same disclaimer
as the charts.
"""

import asyncio
import logging
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

import yfinance as yf

from .indicators import add_indicators, build_levels, nearest_levels

logger = logging.getLogger(__name__)

# A small, liquid IDX default universe. Deliberately not the whole exchange:
# each name costs a yfinance history call, and illiquid tickers produce levels
# finer than the tick size (see chart_generator's tick-size warning).
DEFAULT_UNIVERSE: List[str] = [
    "BBCA.JK", "BBRI.JK", "BMRI.JK", "BBNI.JK", "TLKM.JK", "ASII.JK",
    "UNVR.JK", "ICBP.JK", "INDF.JK", "KLBF.JK", "ADRO.JK", "PTBA.JK",
    "ITMG.JK", "INCO.JK", "ANTM.JK", "SMGR.JK", "INTP.JK", "AKRA.JK",
    "MDKA.JK", "CPIN.JK",
]

# Score weights. Kept as named constants so the ranking can be explained rather
# than tuned by feel.
_W_OVERSOLD = 35        # RSI deep in oversold territory
_W_RSI_RECOVERING = 15  # RSI climbing back out of oversold
_W_UPTREND = 25         # EMA20 > EMA50
_W_ABOVE_EMA20 = 10     # price reclaimed the fast EMA
_W_NEAR_SUPPORT = 15    # sitting close to a defended level


@dataclass
class Pick:
    ticker: str
    score: int
    reasons: List[str]
    last_close: float
    rsi: float
    ema20: float
    ema50: float
    atr: float
    support: Optional[float]
    resistance: Optional[float]
    currency: str
    as_of: str
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _score_one(ticker: str) -> Optional[Pick]:
    """Blocking: one yfinance call + indicator maths. Run via to_thread."""
    try:
        df = yf.Ticker(ticker).history(period="6mo", interval="1d")
        if df is None or df.empty:
            return None
        df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
        df = add_indicators(df)
    except Exception as exc:
        logger.debug("screener.skip ticker=%s error=%s", ticker, exc)
        return None

    last = df.iloc[-1]
    close = float(last["Close"])
    rsi = float(last["rsi14"])
    ema20 = float(last["ema20"])
    ema50 = float(last["ema50"])
    atr = float(last["atr14"])
    if not all(math.isfinite(v) for v in (close, rsi, ema20, ema50, atr)):
        return None

    levels = build_levels(df, atr)
    support, resistance = nearest_levels(close, levels)

    score = 0
    reasons: List[str] = []

    if rsi <= 30:
        score += _W_OVERSOLD
        reasons.append(f"RSI {rsi:.0f} — oversold")
    elif rsi <= 45:
        score += _W_RSI_RECOVERING
        reasons.append(f"RSI {rsi:.0f} — pulih dari tekanan jual")

    if ema20 > ema50:
        score += _W_UPTREND
        reasons.append("EMA20 di atas EMA50 — tren naik")
    if close > ema20:
        score += _W_ABOVE_EMA20
        reasons.append("Harga di atas EMA20")

    if support is not None and atr > 0:
        # "Near" is measured in ATR, not percent, so it means the same thing on
        # a volatile small-cap and a sleepy blue chip.
        distance_atr = (close - support.price) / atr
        if 0 <= distance_atr <= 1.5:
            score += _W_NEAR_SUPPORT
            reasons.append(f"Dekat support {support.price:,.0f}")

    return Pick(
        ticker=ticker,
        score=score,
        reasons=reasons,
        last_close=round(close, 4),
        rsi=round(rsi, 2),
        ema20=round(ema20, 4),
        ema50=round(ema50, 4),
        atr=round(atr, 4),
        support=round(support.price, 4) if support else None,
        resistance=round(resistance.price, 4) if resistance else None,
        currency="IDR" if ticker.endswith(".JK") else "USD",
        as_of=df.index[-1].strftime("%Y-%m-%d"),
    )


async def screen(
    universe: Optional[List[str]] = None,
    max_rsi: int = 100,
    limit: int = 10,
    concurrency: int = 4,
) -> List[Pick]:
    """
    Score `universe` and return the top `limit` picks, best first.

    `max_rsi` filters to names at or below that RSI — the "minimum RSI" control
    in the app maps here (lower = hunting deeper oversold).

    `concurrency` is capped because each task is a blocking yfinance HTTP call
    in a worker thread; unbounded fan-out over 20 tickers would both exhaust the
    default thread pool and hammer Yahoo.
    """
    tickers = universe or DEFAULT_UNIVERSE
    sem = asyncio.Semaphore(concurrency)

    async def one(t: str) -> Optional[Pick]:
        async with sem:
            return await asyncio.to_thread(_score_one, t)

    results = await asyncio.gather(*(one(t) for t in tickers), return_exceptions=True)

    picks: List[Pick] = []
    for r in results:
        if isinstance(r, Pick):
            picks.append(r)
        elif isinstance(r, BaseException):
            logger.debug("screener.task_failed error=%s", r)

    picks = [p for p in picks if p.rsi <= max_rsi and p.score > 0]
    picks.sort(key=lambda p: (-p.score, p.rsi))
    logger.info(
        "screener.done universe=%d scored=%d returned=%d max_rsi=%d",
        len(tickers), len(picks), min(len(picks), limit), max_rsi,
    )
    return picks[:limit]
