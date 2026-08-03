"""
Pure indicator / structure math. No I/O, no plotting — so it stays unit-testable.

Everything here operates on a flat-column OHLCV DataFrame indexed by date, i.e.
what `yfinance.Ticker(...).history()` returns (NOT `yf.download()`, which hands
back MultiIndex columns even for a single ticker).
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator
from ta.volatility import AverageTrueRange

EMA_FAST = 20
EMA_SLOW = 50
RSI_WINDOW = 14
ATR_WINDOW = 14

# Bars on each side required for a swing pivot. 3 keeps minor structure without
# drowning the chart in noise.
SWING_WINDOW = 3


@dataclass(frozen=True)
class Level:
    """A clustered horizontal price level."""

    price: float
    touches: int  # how many swings collapsed into this level — a strength proxy


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Append ema20 / ema50 / rsi14 / atr14 columns. Returns a copy.

    Raises ValueError if there aren't enough bars for the slowest indicator —
    silently emitting an all-NaN EMA50 would produce a chart that looks fine but
    has no trend line on it.
    """
    required = max(EMA_SLOW, RSI_WINDOW, ATR_WINDOW) + 1
    if len(df) < required:
        raise ValueError(
            f"need >= {required} bars for EMA{EMA_SLOW}/RSI{RSI_WINDOW}/ATR{ATR_WINDOW}, got {len(df)}"
        )

    out = df.copy()
    close, high, low = out["Close"], out["High"], out["Low"]

    out["ema20"] = EMAIndicator(close, window=EMA_FAST).ema_indicator()
    out["ema50"] = EMAIndicator(close, window=EMA_SLOW).ema_indicator()
    out["rsi14"] = RSIIndicator(close, window=RSI_WINDOW).rsi()
    out["atr14"] = AverageTrueRange(
        high, low, close, window=ATR_WINDOW
    ).average_true_range()

    # `ta` is inconsistent about warm-up: RSIIndicator yields NaN for its first
    # window-1 bars, but AverageTrueRange yields 0.0. A literal 0 ATR is not
    # "unknown", it reads as "zero volatility" — and volatility is what sizes the
    # stop, so a stray 0 would collapse risk to nothing. Mask it to NaN so the
    # column means the same thing as every other indicator here.
    out.iloc[: ATR_WINDOW - 1, out.columns.get_loc("atr14")] = np.nan
    return out


def find_swings(
    df: pd.DataFrame, window: int = SWING_WINDOW
) -> Tuple[List[float], List[float]]:
    """
    Fractal swing highs/lows: a bar is a swing high if its High is the maximum of
    the +/- `window` bars around it (mirrored for lows).

    NOTE: the last `window` bars are excluded on purpose. A pivot is not
    confirmed until `window` bars have printed after it — including them would
    invent levels that can vanish on the next candle.
    """
    highs, lows = [], []
    h = df["High"].to_numpy()
    l = df["Low"].to_numpy()
    n = len(df)

    for i in range(window, n - window):
        seg_h = h[i - window : i + window + 1]
        seg_l = l[i - window : i + window + 1]
        if h[i] == seg_h.max():
            highs.append(float(h[i]))
        if l[i] == seg_l.min():
            lows.append(float(l[i]))
    return highs, lows


def cluster_levels(levels: List[float], tolerance: float) -> List[Level]:
    """
    Merge levels within `tolerance` of each other into one, averaged, level.

    Without this you get twenty near-identical lines around every congestion
    zone. `touches` records how many raw swings folded in — a level tested five
    times matters more than one tested once.
    """
    if not levels:
        return []
    if tolerance <= 0:
        return [Level(price=p, touches=1) for p in sorted(levels)]

    ordered = sorted(levels)
    clusters: List[List[float]] = [[ordered[0]]]
    for price in ordered[1:]:
        # Compare against the running mean so a long drift doesn't chain-merge
        # everything into one giant cluster.
        current_mean = sum(clusters[-1]) / len(clusters[-1])
        if abs(price - current_mean) <= tolerance:
            clusters[-1].append(price)
        else:
            clusters.append([price])

    return [
        Level(price=float(np.mean(c)), touches=len(c)) for c in clusters
    ]


def pivot_points(high: float, low: float, close: float) -> dict:
    """
    Classic floor-trader pivots from the last completed bar.

    Used as a secondary source of levels — they're formulaic rather than
    price-discovered, so swings take precedence when both are present.
    """
    p = (high + low + close) / 3.0
    return {
        "pivot": p,
        "r1": 2 * p - low,
        "r2": p + (high - low),
        "s1": 2 * p - high,
        "s2": p - (high - low),
    }


def nearest_levels(
    price: float, levels: List[Level]
) -> Tuple[Optional[Level], Optional[Level]]:
    """
    (support, resistance) = nearest clustered level below / above `price`.

    Returns (None, None) components when price is outside the level range —
    e.g. at an all-time high there is no resistance overhead, and saying so is
    more honest than inventing one.
    """
    below = [lv for lv in levels if lv.price < price]
    above = [lv for lv in levels if lv.price > price]
    support = max(below, key=lambda lv: lv.price) if below else None
    resistance = min(above, key=lambda lv: lv.price) if above else None
    return support, resistance


def build_levels(df: pd.DataFrame, atr: float) -> List[Level]:
    """
    Full support/resistance set: confirmed swings + last-bar pivots, clustered
    with an ATR-scaled tolerance so the merge distance adapts to volatility
    instead of using a fixed percentage.
    """
    highs, lows = find_swings(df)
    last = df.iloc[-1]
    piv = pivot_points(float(last["High"]), float(last["Low"]), float(last["Close"]))

    raw = highs + lows + [piv["r1"], piv["r2"], piv["s1"], piv["s2"], piv["pivot"]]
    tolerance = 0.5 * atr if atr > 0 else 0.0
    return cluster_levels(raw, tolerance)
