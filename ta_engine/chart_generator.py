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
from .pattern_detector import (  # noqa: E402
    MIN_QUALITY,
    Pattern,
    detect_patterns,
    detect_rsi_divergence,
)
from .news_context import find_volume_spikes  # noqa: E402
from .price_utils import (  # noqa: E402
    format_price,
    idx_tick_size,
    is_idx_symbol,
    is_index_symbol,
    build_entry_plan,
    round_level,
    round_to_idx_tick,
)

# Pattern geometry is drawn in its own palette. Green/red already mean
# support/TP and resistance/SL on this chart; reusing them for trendlines would
# read as levels rather than boundaries.
_PATTERN_BULL_COLOR = "#22D3EE"
_PATTERN_BEAR_COLOR = "#F472B6"
_PATTERN_NEUTRAL_COLOR = "#A78BFA"

# Blank bars appended to the right of the plot. Without this the newest candles
# and the TP/SL labels are jammed against the y-axis tick labels and the price
# projections have nowhere to sit. Sized so the longest label
# ("Resistance 10,200") clears the last candle with visible whitespace either
# side rather than merely not overlapping it.
_RIGHT_MARGIN_BARS = 22

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

# Tick logic lives in price_utils — one grid definition for the whole system,
# so a level can't be valid on the chart and invalid in the Telegram caption.
_idx_tick_size = idx_tick_size


@dataclass
class ChartResult:
    ticker: str
    chart_path: str
    last_close: float
    support: Optional[float]
    resistance: Optional[float]
    # None for an index — see `trade_direction`.
    tp1: Optional[float]
    tp2: Optional[float]
    sl: Optional[float]
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
    # "long" | "short" | "none". Which way the TP/SL frame reads — it follows
    # the detected pattern so the numbers can't contradict the badge. "none" is
    # an index, where there is no retail instrument to place a level on.
    trade_direction: str = "long"
    # Pattern's own measured move, when one was detected. Derived from the
    # structure rather than from ATR, so it is the pattern's actual thesis.
    pattern_target: Optional[float] = None
    pattern_breakout: Optional[float] = None

    # ── Volume / news linkage ────────────────────────────────────────────
    # Unusual-volume bars, newest first. `headlines` is filled in later by
    # chart_service.attach_news_context, which has DB access; the engine
    # itself stays offline-testable.
    volume_events: List[Dict[str, Any]] = field(default_factory=list)
    volume_summary: Optional[str] = None

    # Latest headlines for this ticker, newest first and UNFILTERED — good
    # and bad alike. Independent of volume: conviction needs the news even
    # on a quiet day. Populated by chart_service.
    recent_news: List[Dict[str, Any]] = field(default_factory=list)

    # ── Entry plan ───────────────────────────────────────────────────────
    # Where to get in. `rr_at_entry` is recomputed at the zone rather than
    # reusing the headline 1:2, which was derived from the last close.
    entry_low: Optional[float] = None
    entry_high: Optional[float] = None
    entry_type: str = "none"          # market | pullback | breakout | none
    breakout_trigger: Optional[float] = None
    rr_at_entry: Optional[float] = None
    entry_note: Optional[str] = None
    entry_extended: bool = False

    # Momentum divergence, when present. An exhaustion warning, not a
    # reversal signal — divergence can persist through a strong trend.
    rsi_divergence: Optional[Dict[str, Any]] = None

    # Valuation snapshot. Filled by chart_service (network call); every
    # metric is bounds-checked, see ta_engine.fundamentals.
    fundamentals: Optional[Dict[str, Any]] = None
    fundamentals_summary: Optional[str] = None

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
    ticker: Optional[str] = None,
    direction: str = "long",
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
    short = direction == "short"

    if short:
        # Mirror image: a breakdown thesis is invalidated by price reclaiming
        # RESISTANCE, so the stop sits above it and targets project downward.
        atr_stop = entry + _ATR_STOP_MULT * atr
        if resistance is not None and resistance.price > entry:
            structure_stop = resistance.price + _SUPPORT_BUFFER_ATR * atr
            # Higher of the two, so a tight ATR stop can't sit inside supply.
            sl = max(atr_stop, structure_stop)
        else:
            sl = atr_stop
            warnings.append(
                "No confirmed resistance above price — stop is ATR-derived only, "
                "with no structural level backing it."
            )
    else:
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

    # Snap the stop onto the IDX grid BEFORE deriving anything from it, then
    # recompute risk from the rounded value. Rounding the stop afterwards would
    # silently break the 1:2 guarantee: a stop nudged toward entry shrinks the
    # real risk denominator while the targets stay where they were. Floor, not
    # nearest, so the snap can only widen the stop — never tighten it into the
    # noise it was sized to survive.
    # Round the stop AWAY from entry in whichever direction widens it, then
    # derive risk from the rounded value.
    if is_idx_symbol(ticker):
        sl = float(round_to_idx_tick(sl, "ceil" if short else "floor"))

    risk = (sl - entry) if short else (entry - sl)
    if risk <= 0 or not math.isfinite(risk):
        raise ValueError(
            f"computed non-positive risk (entry={entry}, sl={sl}); ATR may be zero"
        )

    if short:
        tp1 = entry - _TP1_R * risk
        tp2 = entry - _TP2_R * risk
    else:
        tp1 = entry + _TP1_R * risk
        tp2 = entry + _TP2_R * risk

    # Round targets away from entry too, so rounding never shaves reward below
    # the R multiple.
    if is_idx_symbol(ticker):
        tp_dir = "floor" if short else "ceil"
        tp1 = float(round_to_idx_tick(tp1, tp_dir))
        tp2 = float(round_to_idx_tick(tp2, tp_dir))

    risk_fraction = risk / entry
    if risk_fraction > _MAX_RISK_FRACTION:
        warnings.append(
            f"Stop is {risk_fraction:.1%} {'above' if short else 'below'} entry — "
            f"unusually wide; position sizing matters more than the levels here."
        )

    # A target you can only reach by punching through known structure is not a
    # 2R target in practice. Say so rather than quietly returning it.
    if short:
        if support is not None and support.price > tp1:
            warnings.append(
                f"Support at {support.price:,.2f} sits above TP1 ({tp1:,.2f}) — "
                f"the 1:2 target requires breaking that level first."
            )
        # IDX retail has no practical way to short a single stock, so a
        # breakdown frame is risk management (trim / stand aside), not a trade
        # to place. Saying so prevents it being read as a sell-short signal.
        warnings.append(
            "Bearish setup: IDX retail generally cannot short single stocks, so "
            "these levels describe downside risk and invalidation — not a "
            "short position to open."
        )
    elif resistance is not None and resistance.price < tp1:
        warnings.append(
            f"Resistance at {resistance.price:,.2f} sits below TP1 "
            f"({tp1:,.2f}) — the 1:2 target requires breaking that level first."
        )

    return {
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "risk": risk,
        "direction": direction,
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
    volume_events: Optional[List[Any]] = None,
    entry_plan: Optional[Dict[str, Any]] = None,
) -> None:
    """Candlestick + EMA overlays + green (support/TP) and red (resistance/SL) lines."""
    plot_df = df.tail(plot_bars)
    patterns = patterns or []

    addplots = [
        mpf.make_addplot(plot_df["ema20"], color="#3B9ED6", width=1.1),
        mpf.make_addplot(plot_df["ema50"], color="#F5A623", width=1.1),
    ]

    # An index has no tradeable TP/SL, so only structural levels are drawn.
    show_trade = not is_index_symbol(ticker)
    green = [levels["tp1"], levels["tp2"]] if show_trade else []
    red = [levels["sl"]] if show_trade else []
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
            # Include the horizontal trade levels, not just pattern geometry: in
            # a breakdown frame the stop sits ABOVE price and can land outside
            # the candle range, which clipped its label against the top edge.
            pts = [p for seg in segments for _ts, p in seg]
            pts += [v for v in (green + red) if v is not None]
            if pts:
                y_lo, y_hi = ax.get_ylim()
                span = y_hi - y_lo
                want_lo = min(y_lo, min(pts))
                want_hi = max(y_hi, max(pts))
                # Headroom above is larger: labels are drawn upward from their
                # level, so the topmost one needs a line's worth of clearance.
                ax.set_ylim(
                    max(want_lo, y_lo - span * 0.20),
                    min(want_hi + span * 0.04, y_hi + span * 0.28),
                )

            # IDX prices show as clean integers — sub-rupiah decimals aren't
            # tradeable and imply precision the tick grid doesn't allow.
            cur = "IDR" if is_idx_symbol(ticker) else "USD"
            fmt = lambda v: format_price(v, cur)  # noqa: E731

            # Shade the accumulation zone. A band reads as "anywhere in
            # here", which is what an entry range means — a single line would
            # imply a precision the zone deliberately does not have.
            plan = entry_plan or {}
            if show_trade and plan.get("entry_low") and plan.get("entry_high"):
                lo, hi = plan["entry_low"], plan["entry_high"]
                if hi <= lo:            # collapsed zone: give it visible height
                    pad = max((y_hi - y_lo) * 0.004, 1e-9)
                    lo, hi = lo - pad, hi + pad
                ax.axhspan(lo, hi, color="#22C55E", alpha=0.13, zorder=0)

            annotations = []
            if show_trade:
                # Colour by what the level MEANS in this frame: in a
                # breakdown the targets are below and the stop above, so a
                # fixed green-up/red-down palette would invert the meaning.
                short = levels.get("direction") == "short"
                tp_c = "#F43F5E" if short else "#22C55E"
                sl_c = "#22C55E" if short else "#F43F5E"
                if plan.get("entry_low") and plan.get("entry_high"):
                    zl, zh = plan["entry_low"], plan["entry_high"]
                    label = (
                        f"BELI {fmt(zl)}" if zl == zh
                        else f"BELI {fmt(zl)}–{fmt(zh)}"
                    )
                    annotations.append(((zl + zh) / 2.0, label, "#22C55E"))
                if plan.get("breakout_trigger"):
                    annotations.append(
                        (plan["breakout_trigger"],
                         f"Breakout {fmt(plan['breakout_trigger'])}", "#22D3EE")
                    )
                annotations += [
                    (levels["tp2"], f"TP2 {fmt(levels['tp2'])}", tp_c),
                    (levels["tp1"], f"TP1 {fmt(levels['tp1'])}", tp_c),
                    (levels["sl"], f"SL {fmt(levels['sl'])}", sl_c),
                ]
            # Snap S/R for display the same way the payload does. Formatting the
            # raw level instead would print a number like 4,184 that is not a
            # legal Rp10 tick, and would disagree with the 4,180 the API returns
            # for the same line.
            if support is not None:
                sup_px = round_level(support.price, ticker)
                annotations.append((support.price, f"Support {fmt(sup_px)}", "#22C55E"))
            if resistance is not None:
                res_px = round_level(resistance.price, ticker)
                annotations.append(
                    (resistance.price, f"Resistance {fmt(res_px)}", "#F43F5E")
                )

            # Support / resistance / SL routinely land within a few percent of
            # each other, and right-aligned labels at the same y overlap into an
            # unreadable smear. Nudge each label up until it clears the previous
            # one — the dashed line still marks the true price, the text just
            # gets breathing room.
            #
            # The gap is sized against FONT HEIGHT, not a fixed fraction of the
            # price range: during a tight consolidation the y-range collapses and
            # a percentage gap shrinks with it, so labels would re-collide
            # exactly when the levels are closest together and legibility matters
            # most. Converting the text height back into data units keeps the
            # separation constant on screen at any zoom.
            y_lo, y_hi = ax.get_ylim()
            fig_h_px = fig.get_size_inches()[1] * fig.dpi
            ax_frac = ax.get_position().height
            px_per_data = (fig_h_px * ax_frac) / max(y_hi - y_lo, 1e-9)
            label_px = 13.0                      # ~8pt text plus padding
            min_gap = max(label_px / max(px_per_data, 1e-9), (y_hi - y_lo) * 0.030)
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
                    # Sit inside the blank right margin with real whitespace on
                    # both sides, rather than hugging the axis edge.
                    xytext=(-14, 2),
                    textcoords="offset points",
                    ha="right",
                    va="bottom",
                    fontsize=8,
                    color=color,
                    weight="bold",
                    bbox=dict(
                        boxstyle="round,pad=0.34",
                        facecolor="#0F1521",
                        edgecolor="none",
                        alpha=0.88,
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

            # Project each pattern boundary forward into the blank margin, and
            # mark where the measured move points. Dotted, never solid: the
            # solid part is price that happened, the dotted part is arithmetic
            # about price that has NOT happened. A single line style for both
            # would present a projection as though it were history.
            if patterns and show_trade:
                best_p = patterns[0]
                pos_of = {d: i for i, d in enumerate(plot_df.index)}
                n_vis = len(plot_df)
                proj_color = (
                    _PATTERN_BULL_COLOR if best_p.direction == "bullish"
                    else _PATTERN_BEAR_COLOR if best_p.direction == "bearish"
                    else _PATTERN_NEUTRAL_COLOR
                )
                for seg in best_p.lines:
                    pts = [(pos_of.get(pd.Timestamp(ts)), pr) for ts, pr in seg]
                    pts = [(x, y) for x, y in pts if x is not None]
                    if len(pts) < 2:
                        continue
                    (x0, y0), (x1, y1) = pts[0], pts[-1]
                    if x1 <= x0:
                        continue
                    slope = (y1 - y0) / (x1 - x0)
                    x_end = n_vis - 1 + _RIGHT_MARGIN_BARS
                    ax.plot(
                        [x1, x_end], [y1, y1 + slope * (x_end - x1)],
                        color=proj_color, linestyle=":", linewidth=1.2,
                        alpha=0.75, zorder=2,
                    )

                target = (best_p.key_levels or {}).get("target")
                if target is not None:
                    lo_y, hi_y = ax.get_ylim()
                    x_lab = n_vis - 1 + _RIGHT_MARGIN_BARS * 0.5
                    if target > hi_y:
                        # Measured move sits above the visible range. Pin the
                        # label to the top edge with an arrow rather than
                        # rescaling — BMRI's target is 29% above spot, and
                        # stretching the axis to reach it would flatten every
                        # candle into a line.
                        y_lab, txt = hi_y - (hi_y - lo_y) * 0.03, f"▲ proyeksi {fmt(target)}"
                    elif target < lo_y:
                        y_lab, txt = lo_y + (hi_y - lo_y) * 0.03, f"▼ proyeksi {fmt(target)}"
                    else:
                        y_lab, txt = target, f"proyeksi {fmt(target)}"
                    ax.annotate(
                        txt,
                        xy=(x_lab, y_lab), xycoords="data",
                        ha="center", va="center",
                        fontsize=7.5, color=proj_color, weight="bold",
                        bbox=dict(boxstyle="round,pad=0.28", facecolor="#0F1521",
                                  edgecolor=proj_color, linewidth=0.8, alpha=0.92),
                    )

            # Mark unusual-volume bars on the price panel. These are where the
            # news linkage hangs — the marker says "something happened here",
            # and the payload/caption says what (or that nothing was found).
            if volume_events and len(axes) > 2:
                vol_ax = axes[2]
                visible = {d.strftime("%Y-%m-%d"): i
                           for i, d in enumerate(plot_df.index)}
                for ev in volume_events:
                    ev_date = ev.date if hasattr(ev, "date") else ev.get("date")
                    pos = visible.get(ev_date)
                    if pos is None:
                        continue
                    vol_ax.annotate(
                        "▲",
                        xy=(pos, 0),
                        xycoords=("data", "axes fraction"),
                        xytext=(0, -1),
                        textcoords="offset points",
                        ha="center",
                        va="top",
                        fontsize=7,
                        color="#F5A623",
                        annotation_clip=False,
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
    # Patterns first: the trade frame follows the detected structure. Presenting
    # long targets beneath a "WARNING / BEARISH" badge is a direct
    # contradiction — the badge says price should fall while the numbers
    # describe a buy, and a reader can act on either.
    patterns = detect_patterns(df, min_quality=min_pattern_quality, atr=atr)
    frame = "short" if (patterns and patterns[0].direction == "bearish") else "long"
    trade = _compute_trade_levels(
        entry, atr, support, resistance, ticker=symbol, direction=frame
    )

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
    # "^" leads index symbols (^JKSE) and is unsafe in a URL path, so strip it
    # too rather than emitting "^JKSE_daily.png".
    safe = symbol.replace(".", "_").replace("/", "_").replace("^", "")
    # Daily keeps the historical "_daily" name so existing links stay valid;
    # other intervals are named for what they actually are. A 4-hour chart
    # sitting in a file called "_daily.png" is a trap for anything that reads
    # the path instead of the payload.
    suffix = "daily" if chosen.timeframe == "1d" else chosen.timeframe
    out_path = Path(out_dir) / f"{safe}_{suffix}.png"

    best = patterns[0] if patterns else None
    sentiment = _sentiment_for(best.direction if best else None)
    is_index = is_index_symbol(symbol)
    # Volume spikes are found here; the headlines that explain them are
    # attached downstream where the news cache is reachable.
    volume_events = find_volume_spikes(df)
    divergence = detect_rsi_divergence(df)
    pattern_levels = (best.key_levels if best else {}) or {}

    # Built before rendering: the chart draws the zone, so the plan has to
    # exist first.
    plan = build_entry_plan(
        close=entry,
        atr=atr,
        support=support.price if support else None,
        stop_loss=None if is_index else trade["sl"],
        tp1=None if is_index else trade["tp1"],
        ticker=symbol,
        direction="none" if is_index else trade.get("direction", "long"),
        breakout_level=pattern_levels.get("breakout_level"),
    )

    _render_chart(
        df, symbol, trade, support, resistance, out_path, plot_bars, patterns,
        timeframe=chosen.timeframe, sentiment=sentiment,
        volume_events=volume_events, entry_plan=plan,
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
        # Support/resistance are descriptive, so nearest is right for them.
        # tp/sl were already snapped directionally inside _compute_trade_levels
        # — round_level here is a no-op for IDX and preserves floats elsewhere.
        support=round_level(support.price, symbol) if support else None,
        resistance=round_level(resistance.price, symbol) if resistance else None,
        # An index has no tradeable instrument behind it — IDX retail cannot buy
        # ^JKSE — so quoting entry/target/stop on it invents a position that
        # cannot be taken. Support and resistance still stand as analysis.
        tp1=None if is_index else round_level(trade["tp1"], symbol),
        tp2=None if is_index else round_level(trade["tp2"], symbol),
        sl=None if is_index else round_level(trade["sl"], symbol),
        rsi=round(rsi, 2),
        atr=round(atr, 4),
        ema20=round(float(last["ema20"]), 4),
        ema50=round(float(last["ema50"]), 4),
        risk_per_share=round(trade["risk"], 4),
        risk_reward_tp1=round(_TP1_R, 2),
        risk_reward_tp2=round(_TP2_R, 2),
        # An index (^JKSE) is quoted in points — neither rupiah nor dollars.
        # Labelling IHSG "USD" was wrong and made the levels read as a price.
        currency=(
            "poin" if symbol.startswith("^")
            else "IDR" if symbol.endswith(".JK")
            else "USD"
        ),
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
        trade_direction="none" if is_index else trade.get("direction", "long"),
        pattern_target=round_level(pattern_levels.get("target"), symbol),
        pattern_breakout=round_level(pattern_levels.get("breakout_level"), symbol),
        entry_low=plan["entry_low"],
        entry_high=plan["entry_high"],
        entry_type=plan["entry_type"],
        breakout_trigger=plan["breakout_trigger"],
        rr_at_entry=plan["rr_at_entry"],
        entry_note=plan["note"],
        entry_extended=plan["extended"],
        volume_events=[e.to_dict() for e in volume_events],
        rsi_divergence=divergence,
    )

    logger.info(
        "ta.chart_generated ticker=%s tf=%s close=%.2f sl=%.2f tp1=%.2f tp2=%.2f "
        "rsi=%.1f pattern=%s sentiment=%s warnings=%d",
        symbol, chosen.timeframe, entry, result.sl, result.tp1, result.tp2, rsi,
        result.pattern_name or "none", sentiment, len(warnings),
    )
    return result
