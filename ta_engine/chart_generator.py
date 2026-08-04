"""
Daily technical-analysis chart generator.

Downloads OHLCV via yfinance, computes EMA/RSI/ATR, derives support &
resistance from confirmed swing pivots, sizes a stop and two targets from ATR,
renders an annotated candlestick PNG, and returns the numbers alongside the
image path.

    from ta_engine.chart_generator import generate_chart
    result = generate_chart("BBCA.JK")
    result.chart_path, result.support, result.tp1, result.rsi ...

## IMPORTANT — what these numbers are and are not

TP/SL levels here are **mechanical arithmetic on past prices**, not a
recommendation and not a forecast. They assume a LONG position (the IDX retail
default — shorting is not readily available), so SL sits below entry and targets
above it. `ChartResult.warnings` carries the caveats the maths cannot fix, e.g.
resistance sitting between entry and TP1.

Anything surfacing this to users must present it as analysis with a visible
disclaimer, not as a signal to buy or sell — see DISCLAIMER below.
"""

import logging
import math
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import matplotlib

# Must precede any pyplot import: no display on a server, and Agg is the
# file-rendering backend. Without this, importing this module on a headless
# host can fail or silently pick a GUI backend.
matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import mplfinance as mpf  # noqa: E402
import pandas as pd  # noqa: E402
import yfinance as yf  # noqa: E402

from .indicators import (  # noqa: E402
    ATR_WINDOW,
    EMA_FAST,
    EMA_SLOW,
    RSI_WINDOW,
    Level,
    add_indicators,
    build_levels,
    nearest_levels,
)
from .pattern_detector import MIN_QUALITY, Pattern, detect_patterns  # noqa: E402

# Pattern geometry is drawn in its own palette. Green/red already mean
# support/TP and resistance/SL on this chart; reusing them for trendlines would
# read as levels rather than boundaries.
_PATTERN_BULL_COLOR = "#22D3EE"
_PATTERN_BEAR_COLOR = "#F472B6"
_PATTERN_NEUTRAL_COLOR = "#A78BFA"

# Blank bars appended to the right of the plot. Without this the newest candles
# and the TP/SL labels are jammed against the y-axis tick labels and the price
# projections have nowhere to sit.
_RIGHT_MARGIN_BARS = 12

# Sentiment palette for the corner badge.
_SENTIMENT_STYLE = {
    "BULLISH": ("#22C55E", "BULLISH"),
    "BEARISH_WARNING": ("#F43F5E", "WARNING / BEARISH"),
    "NEUTRAL": ("#F5A623", "NEUTRAL"),
}

# Timeframes scanned, in the order they are tried. yfinance resamples "4h"
# internally (Yahoo itself only serves 1h natively), and intraday history is
# capped — 180d of 4h yields ~345 bars, comfortably past the 51 that EMA50
# needs, while 1y of 4h would be no deeper for the intraday window.
_TIMEFRAMES: List[Tuple[str, str]] = [
    ("1d", "1y"),
    ("4h", "180d"),
]


def _sentiment_for(direction: Optional[str]) -> str:
    """Map a pattern's directional bias to the badge vocabulary."""
    if direction == "bullish":
        return "BULLISH"
    if direction == "bearish":
        return "BEARISH_WARNING"
    return "NEUTRAL"

logger = logging.getLogger(__name__)

DISCLAIMER = (
    "Analisis teknikal otomatis — bukan rekomendasi jual/beli. "
    "Level dihitung dari data harga historis dan dapat berubah. "
    "Risiko investasi ditanggung sendiri."
)

# matplotlib's pyplot layer keeps global state and is not thread-safe. The API
# calls this via asyncio.to_thread, so serialise rendering.
_render_lock = threading.Lock()

_CHART_DIR = Path(__file__).resolve().parent.parent / "static" / "charts"

# Stop distance when there's no usable structure below price.
_ATR_STOP_MULT = 1.5
# Extra room below a support level so ordinary wick noise doesn't trigger the stop.
_SUPPORT_BUFFER_ATR = 0.5
# Reward multiples. TP1 at 2R satisfies the 1:2 minimum by construction.
_TP1_R = 2.0
_TP2_R = 3.0
# A stop wider than this fraction of price means the setup is too loose to size
# sanely — surfaced as a warning rather than silently returned.
_MAX_RISK_FRACTION = 0.15

# IDX tick size bands (fraksi harga), rupiah. Orders can only be placed on these
# increments, so a level finer than the tick is not actually tradeable — e.g. a
# stock pinned at the Rp50 floor can produce a mathematically valid TP that no
# one can enter. Bands are (exclusive upper bound, tick).
_IDX_TICK_BANDS = ((200, 1), (500, 2), (2000, 5), (5000, 10), (float("inf"), 25))


def _idx_tick_size(price: float) -> int:
    """Minimum price increment for an IDX-listed stock at `price`."""
    for upper, tick in _IDX_TICK_BANDS:
        if price < upper:
            return tick
    return 25


@dataclass
class ChartResult:
    ticker: str
    chart_path: str
    last_close: float
    support: Optional[float]
    resistance: Optional[float]
    tp1: float
    tp2: float
    sl: float
    rsi: float
    atr: float
    ema20: float
    ema50: float
    risk_per_share: float
    risk_reward_tp1: float
    risk_reward_tp2: float
    currency: str
    as_of: str
    warnings: List[str] = field(default_factory=list)
    # High-conformance chart patterns found in the window, best first. Usually
    # empty — see `quality_score` in pattern_detector for what the number means
    # (shape conformance, NOT probability of success).
    patterns: List[Dict[str, Any]] = field(default_factory=list)

    # ── Multi-timeframe summary ──────────────────────────────────────────────
    # Which candle interval this chart was actually drawn from. Both 1d and 4h
    # are scanned; the one holding the better-conforming pattern wins, and 1d is
    # the fallback when neither qualifies.
    selected_timeframe: str = "1d"
    pattern_detected: bool = False
    pattern_name: Optional[str] = None
    # "BULLISH" | "BEARISH_WARNING" | "NEUTRAL"
    sentiment: str = "NEUTRAL"
    # Shape conformance of the winning pattern, 0.0 when none qualified. This is
    # geometry, not a probability of the setup working.
    quality_score: float = 0.0

    disclaimer: str = DISCLAIMER

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # `stop_loss` mirrors `sl` so consumers can use either name; `sl` stays
        # for the existing API/Telegram callers.
        d["stop_loss"] = d.get("sl")
        return d


def _fetch_ohlcv(ticker: str, period: str, interval: str) -> pd.DataFrame:
    """
    Daily OHLCV via Ticker().history().

    Deliberately NOT yf.download(): in yfinance 1.2.x that returns MultiIndex
    columns even for a single symbol, which quietly breaks df["Close"].
    """
    df = yf.Ticker(ticker).history(period=period, interval=interval)
    if df is None or df.empty:
        raise ValueError(
            f"no price data for '{ticker}' (delisted, wrong suffix, or bad symbol). "
            f"IDX tickers need the .JK suffix, e.g. BBCA.JK"
        )

    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    if df.empty:
        raise ValueError(f"price data for '{ticker}' was all NaN")

    # mplfinance requires a tz-naive DatetimeIndex; yfinance returns Asia/Jakarta.
    if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df


def _compute_trade_levels(
    entry: float,
    atr: float,
    support: Optional[Level],
    resistance: Optional[Level],
) -> Dict[str, Any]:
    """
    Stop below structure, targets at fixed R multiples.

    The stop goes below the nearest support (buffered by ATR) because that level
    is what invalidates a long thesis — if it breaks, the reason for the trade is
    gone. With no support below price we fall back to a pure ATR stop.

    Targets are then derived from the resulting risk, so the 1:2 minimum holds by
    construction regardless of which stop was used.
    """
    warnings: List[str] = []

    atr_stop = entry - _ATR_STOP_MULT * atr
    if support is not None and support.price < entry:
        structure_stop = support.price - _SUPPORT_BUFFER_ATR * atr
        # Take the lower (safer) of the two so a tight ATR stop can't sit inside
        # a support zone where noise would stop us out.
        sl = min(atr_stop, structure_stop)
    else:
        sl = atr_stop
        warnings.append(
            "No confirmed support below price — stop is ATR-derived only, "
            "with no structural level backing it."
        )

    risk = entry - sl
    if risk <= 0 or not math.isfinite(risk):
        raise ValueError(
            f"computed non-positive risk (entry={entry}, sl={sl}); ATR may be zero"
        )

    tp1 = entry + _TP1_R * risk
    tp2 = entry + _TP2_R * risk

    risk_fraction = risk / entry
    if risk_fraction > _MAX_RISK_FRACTION:
        warnings.append(
            f"Stop is {risk_fraction:.1%} below entry — unusually wide; "
            f"position sizing matters more than the levels here."
        )

    # A target you can only reach by punching through known supply is not a
    # 2R target in practice. Say so rather than quietly returning it.
    if resistance is not None and resistance.price < tp1:
        warnings.append(
            f"Resistance at {resistance.price:,.2f} sits below TP1 "
            f"({tp1:,.2f}) — the 1:2 target requires breaking that level first."
        )

    return {
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "risk": risk,
        "warnings": warnings,
    }


def _pattern_alines(
    patterns: List[Pattern], visible_start: pd.Timestamp
) -> Tuple[List[List[Tuple[Any, float]]], List[str]]:
    """
    Convert detected patterns into mplfinance `alines` segments.

    Points earlier than `visible_start` are clamped to it: a pattern that began
    before the plotted window still shows its geometry rather than being dropped
    or, worse, silently stretching the x-axis back months.
    """
    segments: List[List[Tuple[Any, float]]] = []
    colors: List[str] = []
    for p in patterns:
        # Pattern geometry gets its own colour. Green/red are already spoken
        # for by support/TP vs resistance/SL, and reusing them here would imply
        # a level where there is only a boundary.
        color = _PATTERN_BULL_COLOR if p.direction == "bullish" else _PATTERN_BEAR_COLOR
        if p.direction == "neutral":
            color = _PATTERN_NEUTRAL_COLOR
        for seg in p.lines:
            clipped = [(max(pd.Timestamp(ts), visible_start), price) for ts, price in seg]
            if clipped[0][0] >= clipped[-1][0]:
                continue  # collapsed entirely outside the window
            segments.append(clipped)
            colors.append(color)
    return segments, colors


def _render_chart(
    df: pd.DataFrame,
    ticker: str,
    levels: Dict[str, Any],
    support: Optional[Level],
    resistance: Optional[Level],
    out_path: Path,
    plot_bars: int,
    patterns: Optional[List[Pattern]] = None,
    timeframe: str = "1d",
    sentiment: str = "NEUTRAL",
) -> None:
    """Candlestick + EMA overlays + green (support/TP) and red (resistance/SL) lines."""
    plot_df = df.tail(plot_bars)
    patterns = patterns or []

    addplots = [
        mpf.make_addplot(plot_df["ema20"], color="#3B9ED6", width=1.1),
        mpf.make_addplot(plot_df["ema50"], color="#F5A623", width=1.1),
    ]

    green = [levels["tp1"], levels["tp2"]]
    red = [levels["sl"]]
    if support is not None:
        green.append(support.price)
    if resistance is not None:
        red.append(resistance.price)

    hlines = dict(
        hlines=green + red,
        colors=["#22C55E"] * len(green) + ["#F43F5E"] * len(red),
        linestyle="--",
        linewidths=1.0,
    )

    segments, seg_colors = _pattern_alines(patterns, pd.Timestamp(plot_df.index[0]))
    alines = (
        dict(alines=segments, colors=seg_colors, linestyle="-", linewidths=1.4)
        if segments
        else None
    )

    style = mpf.make_mpf_style(
        base_mpf_style="nightclouds",
        marketcolors=mpf.make_marketcolors(
            up="#22C55E", down="#F43F5E", edge="inherit", wick="inherit", volume="in"
        ),
        facecolor="#0F1521",
        figcolor="#080C14",
        gridcolor="#1E2D40",
    )

    last = df.iloc[-1]
    tf_label = {"1d": "Daily", "4h": "4-Hour", "1h": "1-Hour"}.get(timeframe, timeframe)
    title = (
        f"\n{ticker} — {tf_label}   "
        f"RSI({RSI_WINDOW}) {last['rsi14']:.1f}   ATR({ATR_WINDOW}) {last['atr14']:.2f}"
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)

    with _render_lock:
        try:
            plot_kwargs: Dict[str, Any] = {}
            if alines is not None:
                plot_kwargs["alines"] = alines

            fig, axes = mpf.plot(
                plot_df,
                type="candle",
                style=style,
                addplot=addplots,
                hlines=hlines,
                volume=True,
                figsize=(12, 7),
                title=title,
                ylabel="Harga",
                ylabel_lower="Volume",
                **plot_kwargs,
                returnfig=True,
                tight_layout=True,
            )

            ax = axes[0]

            # Right margin. mplfinance places candles at integer x positions, so
            # widening xlim adds blank space without touching the data — the
            # newest candles and every right-aligned price label stop colliding
            # with the y-axis ticks, and projected TP lines have somewhere to run.
            x_lo, x_hi = ax.get_xlim()
            ax.set_xlim(x_lo, x_hi + _RIGHT_MARGIN_BARS)

            # A fitted boundary can start well above/below the candles it was
            # derived from — a symmetrical triangle's upper line especially.
            # Matplotlib then clips it at the axis and it reads as a rendering
            # glitch (a line entering from nowhere). Give it headroom, but cap
            # the expansion so the candles never get squashed to fit a trendline.
            if segments:
                pts = [p for seg in segments for _ts, p in seg]
                y_lo, y_hi = ax.get_ylim()
                span = y_hi - y_lo
                want_lo = min(y_lo, min(pts))
                want_hi = max(y_hi, max(pts))
                limit = span * 0.20
                ax.set_ylim(
                    max(want_lo, y_lo - limit),
                    min(want_hi, y_hi + limit),
                )

            annotations = [
                (levels["tp2"], f"TP2 {levels['tp2']:,.2f}", "#22C55E"),
                (levels["tp1"], f"TP1 {levels['tp1']:,.2f}", "#22C55E"),
                (levels["sl"], f"SL {levels['sl']:,.2f}", "#F43F5E"),
            ]
            if support is not None:
                annotations.append(
                    (support.price, f"Support {support.price:,.2f}", "#22C55E")
                )
            if resistance is not None:
                annotations.append(
                    (resistance.price, f"Resistance {resistance.price:,.2f}", "#F43F5E")
                )

            # Support / resistance / SL routinely land within a few percent of
            # each other, and right-aligned labels at the same y overlap into an
            # unreadable smear. Nudge each label up until it clears the previous
            # one — the dashed line still marks the true price, the text just
            # gets breathing room.
            y_lo, y_hi = ax.get_ylim()
            min_gap = (y_hi - y_lo) * 0.028
            placed: List[float] = []
            for price, label, color in sorted(annotations, key=lambda a: a[0]):
                y = price
                for prev in placed:
                    if abs(y - prev) < min_gap:
                        y = prev + min_gap
                placed.append(y)
                ax.annotate(
                    label,
                    xy=(1.0, y),
                    xycoords=("axes fraction", "data"),
                    xytext=(-6, 1),
                    textcoords="offset points",
                    ha="right",
                    va="bottom",
                    fontsize=8,
                    color=color,
                    weight="bold",
                    bbox=dict(
                        boxstyle="round,pad=0.22",
                        facecolor="#0F1521",
                        edgecolor="none",
                        alpha=0.75,
                    ),
                )

            # Sentiment badge, top-left. "Quality" is shape conformance, and the
            # label says so — it is not a probability that the setup works.
            badge_color, badge_word = _SENTIMENT_STYLE.get(
                sentiment, _SENTIMENT_STYLE["NEUTRAL"]
            )
            if patterns:
                best = patterns[0]
                badge_text = (
                    f"[{badge_word}]  {best.pattern_type}   "
                    f"(shape quality {best.quality_score * 100:.0f}% | {timeframe.upper()})"
                )
            else:
                badge_text = f"[{badge_word}]  Standard TA — no qualifying pattern | {timeframe.upper()}"

            ax.annotate(
                badge_text,
                xy=(0.012, 0.972),
                xycoords="axes fraction",
                ha="left",
                va="top",
                fontsize=8.5,
                color=badge_color,
                weight="bold",
                bbox=dict(
                    boxstyle="round,pad=0.38",
                    facecolor="#0F1521",
                    edgecolor=badge_color,
                    linewidth=1.1,
                    alpha=0.92,
                ),
            )

            # Secondary patterns, if any, listed under the badge.
            for row, p in enumerate(patterns[1:3]):
                color = (
                    _PATTERN_BULL_COLOR if p.direction == "bullish"
                    else _PATTERN_BEAR_COLOR if p.direction == "bearish"
                    else _PATTERN_NEUTRAL_COLOR
                )
                ax.annotate(
                    f"{p.pattern_type}  ·  {p.quality_score * 100:.0f}%",
                    xy=(0.012, 0.905 - row * 0.048),
                    xycoords="axes fraction",
                    ha="left",
                    va="top",
                    fontsize=7.5,
                    color=color,
                    weight="bold",
                    bbox=dict(
                        boxstyle="round,pad=0.26",
                        facecolor="#0F1521",
                        edgecolor=color,
                        linewidth=0.6,
                        alpha=0.85,
                    ),
                )

            fig.text(
                0.01, 0.01, DISCLAIMER,
                fontsize=6.5, color="#6F80A2", ha="left", va="bottom",
            )

            fig.savefig(out_path, dpi=130, facecolor=fig.get_facecolor())
        finally:
            # Always close, even if savefig raised — a leaked figure keeps its
            # memory for the life of the process.
            plt.close("all")


@dataclass
class _TimeframeAnalysis:
    """Everything computed for one candle interval, before a winner is chosen."""

    timeframe: str
    df: pd.DataFrame
    entry: float
    atr: float
    rsi: float
    support: Optional[Level]
    resistance: Optional[Level]
    trade: Dict[str, Any]
    patterns: List[Pattern]

    @property
    def best_score(self) -> float:
        """Top pattern conformance, or 0.0 when nothing qualified."""
        return self.patterns[0].quality_score if self.patterns else 0.0


def _analyse_timeframe(
    symbol: str, interval: str, period: str, min_pattern_quality: float
) -> _TimeframeAnalysis:
    """Fetch, compute indicators, derive levels and scan patterns for one interval."""
    df = add_indicators(_fetch_ohlcv(symbol, period, interval))

    last = df.iloc[-1]
    entry = float(last["Close"])
    atr = float(last["atr14"])
    rsi = float(last["rsi14"])
    if not math.isfinite(atr) or atr <= 0:
        raise ValueError(f"ATR is {atr} for {symbol} @{interval} — cannot size a stop")

    support, resistance = nearest_levels(entry, build_levels(df, atr))
    trade = _compute_trade_levels(entry, atr, support, resistance)
    patterns = detect_patterns(df, min_quality=min_pattern_quality, atr=atr)

    return _TimeframeAnalysis(
        timeframe=interval,
        df=df,
        entry=entry,
        atr=atr,
        rsi=rsi,
        support=support,
        resistance=resistance,
        trade=trade,
        patterns=patterns,
    )


def generate_chart(
    ticker: str,
    period: Optional[str] = None,
    interval: Optional[str] = None,
    out_dir: Optional[Path] = None,
    plot_bars: int = 120,
    min_pattern_quality: float = MIN_QUALITY,
    multi_timeframe: bool = True,
) -> ChartResult:
    """
    Build the TA chart and levels for `ticker`, choosing the better timeframe.

    Both 1d and 4h are analysed; whichever holds the higher-conforming pattern
    is the one rendered. When neither produces a qualifying pattern the daily
    chart wins by default — it is the more reliable structure and the intraday
    window is short.

    Args:
        ticker: Yahoo symbol. IDX names need the .JK suffix (e.g. "BBCA.JK").
        interval/period: pin a single timeframe instead of scanning. Supplying
            either implies multi_timeframe=False.
        plot_bars: how many recent bars to draw. Indicators still use the full
            period; this only keeps the image readable.
        multi_timeframe: set False to analyse the daily chart alone (cheaper —
            one yfinance download instead of two).

    Returns:
        ChartResult with the PNG path, levels, RSI, chosen timeframe, sentiment
        and any warnings.

    Raises:
        ValueError: unknown/empty symbol, or too few bars for the indicators.
    """
    symbol = ticker.strip().upper()

    # An explicit interval/period is a deliberate pin — honour it and skip the scan.
    if interval is not None or period is not None or not multi_timeframe:
        candidates = [(interval or "1d", period or "1y")]
    else:
        candidates = list(_TIMEFRAMES)

    analyses: List[_TimeframeAnalysis] = []
    errors: List[str] = []
    for tf, per in candidates:
        try:
            analyses.append(_analyse_timeframe(symbol, tf, per, min_pattern_quality))
        except Exception as exc:
            # One timeframe failing (thin intraday history, holiday gaps) must
            # not sink the whole request when the other is fine.
            errors.append(f"{tf}: {exc}")
            logger.info("ta.timeframe_skipped ticker=%s tf=%s error=%s", symbol, tf, exc)

    if not analyses:
        raise ValueError(f"no usable data for '{symbol}' ({'; '.join(errors)})")

    # Highest-conformance pattern wins. Ties (including the all-zero case where
    # nothing qualified anywhere) fall to the earlier entry in _TIMEFRAMES,
    # which is the daily chart.
    chosen = max(analyses, key=lambda a: a.best_score)

    df = chosen.df
    last = df.iloc[-1]
    entry, atr, rsi = chosen.entry, chosen.atr, chosen.rsi
    support, resistance = chosen.support, chosen.resistance
    trade = chosen.trade
    patterns = chosen.patterns

    if len(analyses) > 1:
        logger.info(
            "ta.timeframe_selected ticker=%s chosen=%s scores=%s",
            symbol, chosen.timeframe,
            {a.timeframe: round(a.best_score, 3) for a in analyses},
        )

    out_dir = out_dir or _CHART_DIR
    # Symbol goes into a filename — keep it path-safe ("BBCA.JK" -> "BBCA_JK").
    safe = symbol.replace(".", "_").replace("/", "_")
    # Daily keeps the historical "_daily" name so existing links stay valid;
    # other intervals are named for what they actually are. A 4-hour chart
    # sitting in a file called "_daily.png" is a trap for anything that reads
    # the path instead of the payload.
    suffix = "daily" if chosen.timeframe == "1d" else chosen.timeframe
    out_path = Path(out_dir) / f"{safe}_{suffix}.png"

    best = patterns[0] if patterns else None
    sentiment = _sentiment_for(best.direction if best else None)

    _render_chart(
        df, symbol, trade, support, resistance, out_path, plot_bars, patterns,
        timeframe=chosen.timeframe, sentiment=sentiment,
    )

    warnings = list(trade["warnings"])
    if resistance is None:
        warnings.append(
            "No confirmed resistance above price (near range highs) — "
            "targets are ATR-projected with no structural level to confirm them."
        )

    # An IDX level finer than the tick size cannot be entered as an order,
    # however sound the arithmetic. Common on stocks pinned at the Rp50 floor,
    # where ATR collapses to a few cents.
    if symbol.endswith(".JK"):
        tick = _idx_tick_size(entry)
        if trade["risk"] < tick:
            warnings.append(
                f"Risk per share ({trade['risk']:,.2f}) is below the IDX tick size "
                f"(Rp{tick}) at this price — these levels are not tradeable as "
                f"orders; the stock is too illiquid or price-pinned for ATR sizing."
            )

    result = ChartResult(
        ticker=symbol,
        chart_path=str(out_path),
        last_close=round(entry, 4),
        support=round(support.price, 4) if support else None,
        resistance=round(resistance.price, 4) if resistance else None,
        tp1=round(trade["tp1"], 4),
        tp2=round(trade["tp2"], 4),
        sl=round(trade["sl"], 4),
        rsi=round(rsi, 2),
        atr=round(atr, 4),
        ema20=round(float(last["ema20"]), 4),
        ema50=round(float(last["ema50"]), 4),
        risk_per_share=round(trade["risk"], 4),
        risk_reward_tp1=round(_TP1_R, 2),
        risk_reward_tp2=round(_TP2_R, 2),
        currency="IDR" if symbol.endswith(".JK") else "USD",
        # 4h bars need the time to be meaningful; daily bars don't.
        as_of=df.index[-1].strftime(
            "%Y-%m-%d %H:%M" if chosen.timeframe != "1d" else "%Y-%m-%d"
        ),
        warnings=warnings,
        patterns=[p.to_dict() for p in patterns],
        selected_timeframe=chosen.timeframe,
        pattern_detected=best is not None,
        pattern_name=best.pattern_type if best else None,
        sentiment=sentiment,
        quality_score=best.quality_score if best else 0.0,
    )

    logger.info(
        "ta.chart_generated ticker=%s tf=%s close=%.2f sl=%.2f tp1=%.2f tp2=%.2f "
        "rsi=%.1f pattern=%s sentiment=%s warnings=%d",
        symbol, chosen.timeframe, entry, result.sl, result.tp1, result.tp2, rsi,
        result.pattern_name or "none", sentiment, len(warnings),
    )
    return result
