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
from typing import Any, Dict, List, Optional

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
    disclaimer: str = DISCLAIMER

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


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


def _render_chart(
    df: pd.DataFrame,
    ticker: str,
    levels: Dict[str, Any],
    support: Optional[Level],
    resistance: Optional[Level],
    out_path: Path,
    plot_bars: int,
) -> None:
    """Candlestick + EMA overlays + green (support/TP) and red (resistance/SL) lines."""
    plot_df = df.tail(plot_bars)

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
    title = (
        f"\n{ticker} — Daily   "
        f"RSI({RSI_WINDOW}) {last['rsi14']:.1f}   ATR({ATR_WINDOW}) {last['atr14']:.2f}"
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)

    with _render_lock:
        try:
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
                returnfig=True,
                tight_layout=True,
            )

            ax = axes[0]
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

            fig.text(
                0.01, 0.01, DISCLAIMER,
                fontsize=6.5, color="#6F80A2", ha="left", va="bottom",
            )

            fig.savefig(out_path, dpi=130, facecolor=fig.get_facecolor())
        finally:
            # Always close, even if savefig raised — a leaked figure keeps its
            # memory for the life of the process.
            plt.close("all")


def generate_chart(
    ticker: str,
    period: str = "1y",
    interval: str = "1d",
    out_dir: Optional[Path] = None,
    plot_bars: int = 120,
) -> ChartResult:
    """
    Build the daily TA chart and levels for `ticker`.

    Args:
        ticker: Yahoo symbol. IDX names need the .JK suffix (e.g. "BBCA.JK").
        period: yfinance lookback for the CALCULATION window (needs >= ~60 bars
            so EMA50 is defined).
        plot_bars: how many recent bars to actually draw. Indicators still use
            the full period; this only keeps the image readable.

    Returns:
        ChartResult with the PNG path, levels, RSI and any warnings.

    Raises:
        ValueError: unknown/empty symbol, or too few bars for the indicators.
    """
    symbol = ticker.strip().upper()
    df = _fetch_ohlcv(symbol, period, interval)
    df = add_indicators(df)

    last = df.iloc[-1]
    entry = float(last["Close"])
    atr = float(last["atr14"])
    rsi = float(last["rsi14"])

    if not math.isfinite(atr) or atr <= 0:
        raise ValueError(f"ATR is {atr} for {symbol} — cannot size a stop")

    all_levels = build_levels(df, atr)
    support, resistance = nearest_levels(entry, all_levels)
    trade = _compute_trade_levels(entry, atr, support, resistance)

    out_dir = out_dir or _CHART_DIR
    # Symbol goes into a filename — keep it path-safe ("BBCA.JK" -> "BBCA_JK").
    safe = symbol.replace(".", "_").replace("/", "_")
    out_path = Path(out_dir) / f"{safe}_daily.png"

    _render_chart(df, symbol, trade, support, resistance, out_path, plot_bars)

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
        as_of=df.index[-1].strftime("%Y-%m-%d"),
        warnings=warnings,
    )

    logger.info(
        "ta.chart_generated ticker=%s close=%.2f sl=%.2f tp1=%.2f tp2=%.2f rsi=%.1f warnings=%d",
        symbol, entry, result.sl, result.tp1, result.tp2, rsi, len(warnings),
    )
    return result
