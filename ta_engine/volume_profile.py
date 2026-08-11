"""
Volume profile: where the shares actually changed hands.

Support and resistance derived from swing pivots answer "where did price turn?".
A volume profile answers a different and complementary question: "where did the
most trading happen?" Those are not the same place, and the difference matters —
a level with a lot of volume behind it has real inventory to absorb or supply,
while a sharp reversal on thin volume is a level almost nobody is positioned at.

Three outputs, the standard market-profile vocabulary:

* **POC** (Point of Control) — the single price bin with the most volume. The
  price this market agreed on most often.
* **VAH / VAL** (Value Area High / Low) — the tightest band around the POC
  holding `VALUE_AREA_PCT` of all volume. Price inside the value area is
  "accepted"; price outside it is being rejected or is in discovery.

## The approximation, stated plainly

True volume-at-price needs tick or order-book data. We have daily OHLCV, so each
bar's volume is spread UNIFORMLY across its high-low range. That overstates
volume at the extremes of wide bars and understates it around the close, where
in reality most business is done.

It is still far better than the alternative of ignoring volume, and the shape of
the profile — where the peak sits, how wide the value area is — is robust to
this assumption even though the exact per-bin numbers are not. Anything shown to
a user should be framed as "roughly where volume concentrated", never as an
exact figure.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

# Share of total volume defining the value area. 70% is the market-profile
# convention (roughly one standard deviation of a normal distribution).
VALUE_AREA_PCT = 0.70

# Bin width in ATR. Fine enough to locate the POC meaningfully, coarse enough
# that a single bar's range still spans several bins.
BIN_ATR = 0.25
# Hard bounds on bin count: too few and the POC is meaningless, too many and
# each bin holds noise.
MIN_BINS = 20
MAX_BINS = 160

# Default window, in bars. Chosen by measurement, not convention: over a full
# year the value area came out ~32% of price wide and EVERY name read "inside
# value", which is no information at all. At 60 bars (~3 months) the median
# width is 14% and names start falling outside it. Market profile is a
# statement about where value is NOW; a year of history dilutes it into a
# statement about nothing.
DEFAULT_LOOKBACK_BARS = 60

# A value area wider than this fraction of the POC is not usable as "value" —
# it means volume is smeared across the whole range rather than concentrated.
# Reported as such instead of being dressed up as a level.
WIDE_VA_RATIO = 0.45


@dataclass(frozen=True)
class VolumeProfile:
    poc: float           # price of the highest-volume bin (bin centre)
    val: float           # value area low
    vah: float           # value area high
    bin_width: float
    # (centre_price, volume) per bin, low price first. Kept for charting.
    bins: List[Tuple[float, float]]
    total_volume: float

    @property
    def is_wide(self) -> bool:
        """
        True when volume is spread too broadly for the value area to mean
        anything — e.g. ASPR, which ran 99 -> 620 -> 156 and has real volume
        at every price in between. Honest output says so rather than quoting a
        160%-wide band as though it were a level.
        """
        return self.poc > 0 and (self.vah - self.val) / self.poc > WIDE_VA_RATIO

    def contains(self, low: float, high: float) -> bool:
        """Does a price band overlap the value area?"""
        return low <= self.vah and self.val <= high

    def volume_between(self, low: float, high: float) -> float:
        """
        Fraction of total volume that traded inside [low, high].

        Uses the binned profile rather than re-walking the bars, so every
        volume figure in the system comes from one place and cannot disagree
        with the profile drawn on the chart.
        """
        if self.total_volume <= 0 or high < low:
            return 0.0
        half = self.bin_width / 2.0
        inside = sum(
            v for c, v in self.bins
            if (c + half) > low and (c - half) < high
        )
        return inside / self.total_volume


def build_profile(
    df: pd.DataFrame,
    atr: float,
    bars: Optional[int] = DEFAULT_LOOKBACK_BARS,
) -> Optional[VolumeProfile]:
    """
    Volume profile over the last `bars` bars. Pass bars=None for the whole frame.

    Returns None when the frame has no usable volume — index frames and
    thinly-traded names, where a profile would be fabricated from nothing.
    """
    if "Volume" not in df.columns or len(df) < 5 or atr <= 0:
        return None
    if bars:
        df = df.tail(bars)

    highs = df["High"].to_numpy(dtype=float)
    lows = df["Low"].to_numpy(dtype=float)
    vols = np.nan_to_num(df["Volume"].to_numpy(dtype=float), nan=0.0)

    total = float(vols.sum())
    if total <= 0:
        return None

    lo, hi = float(np.nanmin(lows)), float(np.nanmax(highs))
    if not math.isfinite(lo) or not math.isfinite(hi) or hi <= lo:
        return None

    n_bins = int(round((hi - lo) / max(BIN_ATR * atr, 1e-9)))
    n_bins = max(MIN_BINS, min(MAX_BINS, n_bins))
    edges = np.linspace(lo, hi, n_bins + 1)
    width = float(edges[1] - edges[0])
    hist = np.zeros(n_bins, dtype=float)

    # Spread each bar's volume across the bins its range covers, weighted by how
    # much of the bin the bar actually overlaps. Partial overlaps matter: a
    # narrow doji inside one bin should not be smeared across three.
    for h, l, v in zip(highs, lows, vols):
        if v <= 0 or not math.isfinite(h) or not math.isfinite(l):
            continue
        span = max(h - l, 1e-9)
        first = max(0, int((l - lo) // width))
        last = min(n_bins - 1, int((h - lo) // width))
        for b in range(first, last + 1):
            b_lo, b_hi = edges[b], edges[b + 1]
            overlap = min(h, b_hi) - max(l, b_lo)
            if overlap > 0:
                hist[b] += v * (overlap / span)

    if hist.sum() <= 0:
        return None

    centres = (edges[:-1] + edges[1:]) / 2.0
    poc_idx = int(np.argmax(hist))

    # Value area: start at the POC and repeatedly annex whichever adjacent bin
    # holds more volume, until VALUE_AREA_PCT is enclosed. This is the standard
    # construction — it grows toward volume rather than symmetrically, so the
    # band ends up skewed the way the market actually traded.
    target = hist.sum() * VALUE_AREA_PCT
    low_i = high_i = poc_idx
    acc = hist[poc_idx]
    while acc < target and (low_i > 0 or high_i < n_bins - 1):
        below = hist[low_i - 1] if low_i > 0 else -1.0
        above = hist[high_i + 1] if high_i < n_bins - 1 else -1.0
        if above >= below:
            high_i += 1
            acc += hist[high_i]
        else:
            low_i -= 1
            acc += hist[low_i]

    return VolumeProfile(
        poc=float(centres[poc_idx]),
        val=float(edges[low_i]),
        vah=float(edges[high_i + 1]),
        bin_width=width,
        bins=[(float(c), float(v)) for c, v in zip(centres, hist)],
        total_volume=total,
    )


def describe(profile: Optional[VolumeProfile], price: float, fmt=None) -> str:
    """
    One-line reading of where price sits relative to the traded volume.

    Deliberately descriptive, never prescriptive: "price is above the value
    area" is an observation, not a signal. Both breakout continuation and
    mean-reversion are common from there, and saying which would be a forecast.
    """
    if profile is None:
        return ""
    f = fmt or (lambda v: f"{v:,.0f}")

    if profile.is_wide:
        return (
            f"Volume tersebar sangat lebar ({f(profile.val)}–{f(profile.vah)}) — "
            f"tidak ada area nilai yang jelas, jadi jangan dipakai sebagai level. "
            f"Bin paling padat ada di <b>{f(profile.poc)}</b>."
        )

    if price > profile.vah:
        where = (
            f"Harga di ATAS area nilai ({f(profile.val)}–{f(profile.vah)}) — "
            f"sedang di wilayah yang jarang ditransaksikan"
        )
    elif price < profile.val:
        where = (
            f"Harga di BAWAH area nilai ({f(profile.val)}–{f(profile.vah)}) — "
            f"sedang di wilayah yang jarang ditransaksikan"
        )
    else:
        where = f"Harga di DALAM area nilai ({f(profile.val)}–{f(profile.vah)})"

    return f"{where}. Volume paling padat di <b>{f(profile.poc)}</b> (POC)."
