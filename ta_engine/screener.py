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
from .pattern_detector import detect_patterns, detect_rsi_divergence

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

# ── Structure weights ────────────────────────────────────────────────────────
# Scaled by the pattern's shape quality, so a 0.95 Double Bottom counts for more
# than a marginal 0.81 one. Quality is geometric conformance, NOT a probability
# — see pattern_detector — so it is used to rank, never to imply a hit rate.
_W_PATTERN_BULLISH = 30
# Bearish structure is a PENALTY, not merely an absent bonus. This screener
# hunts long setups; surfacing a name that is simultaneously printing a Head and
# Shoulders is the same contradiction the chart had when a bearish badge sat
# above long targets. Weighted heavier than the bullish bonus so a clean
# breakdown can cancel an oversold reading outright and drop the name.
_W_PATTERN_BEARISH = -40
_W_DIVERGENCE_BULL = 12   # momentum improving while price makes lower lows
_W_DIVERGENCE_BEAR = -18  # price making highs on fading momentum

# ── Fundamental weights (opt-in; see `with_fundamentals`) ────────────────────
# Small by design. These are vendor figures that lag their filings and are
# unreliable enough on IDX to need validation, so they nudge the ranking rather
# than drive it.
_W_CHEAP_PER = 10       # PER under _PER_CHEAP
_W_STRONG_ROE = 10      # ROE over _ROE_STRONG
_W_DIVIDEND = 8         # yield over _YIELD_GOOD
_PER_CHEAP = 15.0
_ROE_STRONG = 15.0
_YIELD_GOOD = 4.0
# Above this a yield is more likely a symptom of a falling price than a
# generous payout, and gets flagged rather than presented as a clean positive.
_YIELD_SUSPICIOUS = 10.0


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

    # ── Structure ────────────────────────────────────────────────────────────
    pattern_name: Optional[str] = None
    pattern_quality: float = 0.0
    pattern_direction: Optional[str] = None
    divergence: Optional[str] = None
    # Set when bearish structure dragged the score down. Surfaced so a name
    # missing from the results can be explained rather than just absent.
    penalised: bool = False

    # ── Fundamentals (only when `with_fundamentals=True`) ────────────────────
    per: Optional[float] = None
    pbv: Optional[float] = None
    roe_percent: Optional[float] = None
    dividend_yield_percent: Optional[float] = None
    sector: Optional[str] = None

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

    # ── Chart structure ──────────────────────────────────────────────────────
    # Free: the dataframe is already in hand, so this costs no extra network.
    pattern_name = pattern_direction = None
    pattern_quality = 0.0
    penalised = False
    try:
        found = detect_patterns(df, atr=atr)
    except Exception as exc:
        logger.debug("screener.pattern_failed ticker=%s error=%s", ticker, exc)
        found = []

    if found:
        best = found[0]
        pattern_name = best.pattern_type
        pattern_quality = best.quality_score
        pattern_direction = best.direction
        if best.direction == "bullish":
            pts = int(round(_W_PATTERN_BULLISH * best.quality_score))
            score += pts
            reasons.append(
                f"{best.pattern_type} — pola bullish "
                f"(kemiripan bentuk {best.quality_score * 100:.0f}%)"
            )
        elif best.direction == "bearish":
            pts = int(round(_W_PATTERN_BEARISH * best.quality_score))
            score += pts
            penalised = True
            reasons.append(
                f"⚠️ {best.pattern_type} — struktur BEARISH "
                f"({best.quality_score * 100:.0f}%), skor dipotong"
            )

    divergence = None
    try:
        div = detect_rsi_divergence(df)
    except Exception:
        div = None
    if div:
        divergence = div["type"]
        if div["direction"] == "bullish":
            score += _W_DIVERGENCE_BULL
            reasons.append("Divergensi RSI bullish — momentum membaik")
        else:
            score += _W_DIVERGENCE_BEAR
            penalised = True
            reasons.append("⚠️ Divergensi RSI bearish — momentum melemah")

    return Pick(
        pattern_name=pattern_name,
        pattern_quality=round(pattern_quality, 4),
        pattern_direction=pattern_direction,
        divergence=divergence,
        penalised=penalised,
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


def _apply_fundamentals(pick: Pick) -> Pick:
    """
    Fold validated valuation metrics into an already-scored pick.

    Separate from `_score_one` because it costs a SECOND network call per
    ticker (yfinance `.info`), which would double the cost of a 20-name sweep.
    Only applied to the shortlist, and only when explicitly requested.

    Metrics that failed validation are absent, so a name is never penalised for
    Yahoo returning a broken PBV — see ta_engine.fundamentals.
    """
    from .fundamentals import fetch_fundamentals

    try:
        f = fetch_fundamentals(pick.ticker)
    except Exception as exc:
        logger.debug("screener.fundamentals_failed ticker=%s error=%s", pick.ticker, exc)
        return pick

    pick.per = f.per
    pick.pbv = f.pbv
    pick.roe_percent = f.roe_percent
    pick.dividend_yield_percent = f.dividend_yield_percent
    pick.sector = f.sector

    if f.per is not None and f.per <= _PER_CHEAP:
        pick.score += _W_CHEAP_PER
        pick.reasons.append(f"PER {f.per:.1f}x — valuasi relatif murah")
    if f.roe_percent is not None and f.roe_percent >= _ROE_STRONG:
        pick.score += _W_STRONG_ROE
        pick.reasons.append(f"ROE {f.roe_percent:.0f}% — profitabilitas kuat")
    if (
        f.dividend_yield_percent is not None
        and f.dividend_yield_percent >= _YIELD_GOOD
    ):
        pick.score += _W_DIVIDEND
        note = f"Dividend yield {f.dividend_yield_percent:.1f}%"
        # Yield is dividend/price, so a collapsing price inflates it. Measured
        # on this universe: BBRI shows ~13% while sitting 27% below its 52-week
        # high — that is the denominator shrinking, not the payout growing.
        # Rewarding it without saying so points the screener at falling knives.
        if f.dividend_yield_percent >= _YIELD_SUSPICIOUS:
            note += (
                " — <i>setinggi ini biasanya karena harga turun tajam, "
                "bukan dividen naik; cek keberlanjutannya</i>"
            )
        pick.reasons.append(note)
    return pick


async def screen(
    universe: Optional[List[str]] = None,
    max_rsi: int = 100,
    limit: int = 10,
    concurrency: int = 4,
    with_fundamentals: bool = False,
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

    rejected = [p for p in picks if p.penalised and p.score <= 0]
    picks = [p for p in picks if p.rsi <= max_rsi and p.score > 0]
    picks.sort(key=lambda p: (-p.score, p.rsi))

    # Fundamentals only for the shortlist: applying them to the whole universe
    # would double the network cost for names about to be discarded anyway.
    if with_fundamentals and picks:
        head = picks[: limit * 2]
        enriched = await asyncio.gather(
            *(asyncio.to_thread(_apply_fundamentals, p) for p in head),
            return_exceptions=True,
        )
        head = [p for p in enriched if isinstance(p, Pick)]
        head.sort(key=lambda p: (-p.score, p.rsi))
        picks = head + picks[limit * 2 :]

    logger.info(
        "screener.done universe=%d scored=%d returned=%d rejected_bearish=%d "
        "max_rsi=%d fundamentals=%s",
        len(tickers), len(picks), min(len(picks), limit), len(rejected),
        max_rsi, with_fundamentals,
    )
    if rejected:
        # Worth logging: these are names an RSI-only screen WOULD have
        # surfaced, dropped because their structure contradicts a long.
        logger.info(
            "screener.bearish_rejects %s",
            [(p.ticker, p.pattern_name) for p in rejected],
        )
    return picks[:limit]
