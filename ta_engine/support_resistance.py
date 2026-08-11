"""
Scored support/resistance ZONES.

Replaces the single-price levels in `indicators.py` for anything user-facing.
Three things were wrong with treating support as one number:

1. **A level is a band, not a price.** Price reacts to a region. Averaging a
   cluster of swings into one float throws away the only information that says
   how wide the reaction area actually is.
2. **Nearest is not strongest.** The old code anchored the stop under whichever
   level was closest, so a single-touch scribble 1% away beat a six-touch shelf
   4% away. The stop then hung off the flimsiest structure available.
3. **Strength was never measured.** `Level.touches` existed but nothing read it,
   and it was inflated anyway: floor-trader pivots (five arithmetic values off
   the last bar) were poured into the same cluster list as real swing pivots and
   each one incremented the count.

## What "strength" means here

A zone's score is **structural evidence, not probability**. A KUAT zone has been
tested repeatedly, mostly held, recently, with real volume traded inside it. It
is NOT "80% likely to hold" and must never be presented as odds. Support breaks
all the time; the score says how much history is behind the level, nothing more.

Five components, each normalised to 0..1:

| component  | why it matters                                                |
|------------|---------------------------------------------------------------|
| tests      | one touch is an accident, four is a shelf (saturates at 4)     |
| hold ratio | a level tested 5× that broke twice is weak — this is the crux  |
| recency    | structure decays; a 2019 low is archaeology (exponential)      |
| volume     | the real floor is where size changed hands, not where it wicked |
| span       | respected across months > respected across three days          |

Weights favour hold ratio and test count because those are direct evidence of
the level doing its job. Volume is weighted lowest: it is approximated from
bar ranges, not from true volume-at-price (tick data, which we don't have).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

# Bars on each side required to confirm a swing pivot. Matches indicators.py.
SWING_WINDOW = 3

# A zone is at least this wide in ATR terms, so a single-pivot zone still has a
# band instead of degenerating back into a line.
MIN_ZONE_ATR = 0.30
# Two swings merge into one zone if they sit within this much ATR of each other.
CLUSTER_ATR = 0.60
# Widest a zone may grow; beyond this it is congestion, not a level.
MAX_ZONE_ATR = 2.00

# Test counting saturates here — beyond four tests, more touches say little.
TESTS_SATURATE = 4
# Recency half-life in bars: a zone last tested this long ago scores 0.5.
RECENCY_HALFLIFE_BARS = 45.0
# Volume share (of total period volume) treated as "a lot traded here".
VOLUME_SATURATE = 0.15
# Span (bars between first and last test) treated as fully established.
SPAN_SATURATE = 60.0

# Price must close this far outside the band before re-entry counts as a test,
# rather than as chop inside its own congestion.
APPROACH_ATR = 0.30

# PROMINENCE — how much history sits at this price. Hold ratio is deliberately
# absent: it multiplies the result instead (see _score_zone).
_PROMINENCE_WEIGHTS: Dict[str, float] = {
    "tests": 0.36,
    "recency": 0.28,
    "volume": 0.21,
    "span": 0.15,
}

# A zone that always breaks still keeps this much of its prominence: it marks a
# price that matters, it just isn't reliable.
RELIABILITY_FLOOR = 0.45

# Reliability caps on the label, applied once there is a real record to judge.
STRONG_HOLD_RATIO = 0.60   # below this it cannot be called KUAT
WEAK_HOLD_RATIO = 0.40     # below this it is LEMAH whatever the score
MIN_RESOLVED_FOR_CAP = 3   # don't punish young levels for thin evidence

# Score thresholds. Deliberately demanding: calling something KUAT should mean
# something, so most zones on a typical chart land in SEDANG or LEMAH.
STRONG_MIN = 0.62
MEDIUM_MIN = 0.38

_LABELS = {"strong": "KUAT", "medium": "SEDANG", "weak": "LEMAH"}


@dataclass(frozen=True)
class Zone:
    """A scored horizontal price band."""

    low: float
    high: float
    mid: float
    # "support" | "resistance" — assigned relative to current price, so the same
    # band flips role when price crosses it.
    kind: str
    # True when the band was formed from BOTH swing highs and swing lows: old
    # resistance that became support (or vice versa). A genuine polarity flip is
    # meaningful structure, so it earns a small bonus.
    flipped: bool
    tests: int
    holds: int
    breaks: int
    bars_since_test: int
    volume_share: float
    span_bars: int
    score: float
    strength: str          # "strong" | "medium" | "weak"

    @property
    def label(self) -> str:
        """Indonesian strength word for the bot."""
        return _LABELS[self.strength]

    @property
    def width(self) -> float:
        return self.high - self.low

    def evidence(self) -> str:
        """
        One-line justification, in Indonesian.

        Always shown next to the label so the reader can judge the call instead
        of trusting it — the counts are the actual claim, the word is a summary.
        """
        bits = [f"{self.tests} tes"]
        if self.tests:
            bits.append(f"{self.holds} bertahan")
        if self.breaks:
            bits.append(f"{self.breaks} jebol")
        bits.append(f"terakhir {self.bars_since_test} bar lalu")
        if self.volume_share >= 0.02:
            bits.append(f"{self.volume_share * 100:.0f}% volume")
        if self.flipped:
            bits.append("bekas resisten")
        return " · ".join(bits)


# ── Swing detection (index-aware, unlike indicators.find_swings) ─────────────


def find_swing_points(
    df: pd.DataFrame, window: int = SWING_WINDOW
) -> List[Tuple[int, float, str]]:
    """
    Confirmed fractal pivots as (bar_index, price, "high"|"low").

    The last `window` bars are excluded: a pivot isn't confirmed until `window`
    bars have printed after it, and including them invents levels that vanish on
    the next candle.
    """
    highs = df["High"].to_numpy(dtype=float)
    lows = df["Low"].to_numpy(dtype=float)
    out: List[Tuple[int, float, str]] = []

    for i in range(window, len(df) - window):
        seg_h = highs[i - window : i + window + 1]
        seg_l = lows[i - window : i + window + 1]
        if highs[i] == seg_h.max():
            out.append((i, float(highs[i]), "high"))
        if lows[i] == seg_l.min():
            out.append((i, float(lows[i]), "low"))
    return out


# ── Zone construction ────────────────────────────────────────────────────────


def _cluster_pivots(
    pivots: Sequence[Tuple[int, float, str]], atr: float
) -> List[List[Tuple[int, float, str]]]:
    """
    Group pivots into price bands.

    Compares each pivot against the running MEAN of the open cluster (not its
    last member) so a slow drift can't chain-merge an entire chart into one
    band, and hard-caps total width at MAX_ZONE_ATR for the same reason.
    """
    if not pivots:
        return []

    tol = CLUSTER_ATR * atr
    max_width = MAX_ZONE_ATR * atr
    ordered = sorted(pivots, key=lambda p: p[1])

    clusters: List[List[Tuple[int, float, str]]] = [[ordered[0]]]
    for piv in ordered[1:]:
        current = clusters[-1]
        mean = sum(p[1] for p in current) / len(current)
        lo = min(p[1] for p in current)
        if abs(piv[1] - mean) <= tol and (piv[1] - lo) <= max_width:
            current.append(piv)
        else:
            clusters.append([piv])
    return clusters


def _count_tests(
    df: pd.DataFrame, low: float, high: float, atr: float
) -> Tuple[int, int, int, int, int]:
    """
    Walk the bars and score how the zone actually behaved.

    Returns (tests, holds, breaks, bars_since_last_test, span_bars).

    A "test" is an EPISODE, not a bar: price entering the band and staying there
    for six bars is one test, not six. Counting bars would let a single long
    consolidation masquerade as a heavily respected level.

    An episode only counts as a test if price APPROACHED from clearly outside —
    the prior close must sit at least APPROACH_ATR beyond an edge. Without this
    a stock chopping around its own congestion racks up "tests" it never really
    made: on a first pass UNVR showed 14 tests of a band 0.3 ATR wide that price
    was simply oscillating inside.

    Outcome of an episode:
      * hold  — price left and closed back on the side it came from
      * break — price closed clear of the far side

    Episodes still open at the last bar count as tests but score neither hold
    nor break: the outcome genuinely isn't known yet.
    """
    highs = df["High"].to_numpy(dtype=float)
    lows = df["Low"].to_numpy(dtype=float)
    closes = df["Close"].to_numpy(dtype=float)
    n = len(df)
    buf = APPROACH_ATR * atr

    tests = holds = breaks = 0
    first_test: Optional[int] = None
    last_test: Optional[int] = None

    i = 0
    while i < n:
        # Bar overlaps the band at all?
        if not (lows[i] <= high and highs[i] >= low):
            i += 1
            continue

        start = i
        # Consume the whole episode first, so `i` lands on the exit bar.
        while i < n and lows[i] <= high and highs[i] >= low:
            i += 1

        if start == 0:
            continue  # no prior bar — approach direction unknowable

        prior = closes[start - 1]
        if prior > high + buf:
            from_above = True
        elif prior < low - buf:
            from_above = False
        else:
            continue  # drifted in from inside the band: chop, not a test

        tests += 1
        first_test = start if first_test is None else first_test
        last_test = i - 1

        if i >= n:
            break  # still open — outcome unknown
        if from_above:
            # Came down into it: holding means closing back above the band.
            if closes[i] > high:
                holds += 1
            elif closes[i] < low:
                breaks += 1
        else:
            # Came up into it: holding means being rejected back below.
            if closes[i] < low:
                holds += 1
            elif closes[i] > high:
                breaks += 1

    bars_since = (n - 1 - last_test) if last_test is not None else n
    span = (last_test - first_test) if (first_test is not None and last_test is not None) else 0
    return tests, holds, breaks, int(bars_since), int(span)


def _volume_share(df: pd.DataFrame, low: float, high: float) -> float:
    """
    Fraction of period volume that traded inside the band.

    True volume-at-price needs tick data we don't have, so each bar's volume is
    spread UNIFORMLY across its high-low range and we take the overlapping
    slice. That is an approximation — it overstates volume at the extremes of
    wide bars — but it is far closer to reality than ignoring volume entirely,
    which is what the previous code did.
    """
    if "Volume" not in df.columns:
        return 0.0

    highs = df["High"].to_numpy(dtype=float)
    lows = df["Low"].to_numpy(dtype=float)
    vols = df["Volume"].to_numpy(dtype=float)

    total = float(np.nansum(vols))
    if total <= 0:
        return 0.0

    spans = np.maximum(highs - lows, 1e-9)
    overlap = np.clip(np.minimum(highs, high) - np.maximum(lows, low), 0.0, None)
    inside = float(np.nansum(vols * np.clip(overlap / spans, 0.0, 1.0)))
    return inside / total


def _score_zone(
    tests: int,
    holds: int,
    breaks: int,
    bars_since: int,
    volume_share: float,
    span: int,
    flipped: bool,
) -> Tuple[float, float, Dict[str, float]]:
    """
    (score, hold_ratio, components) — the maths stays inspectable on purpose.

    Hold ratio is a MULTIPLIER, not a summand. A purely additive score let a
    level score highly on sheer activity while failing at its actual job: the
    first calibration run rated a PGAS band KUAT on "15 tes · 6 bertahan · 9
    jebol" — it broke more often than it held. Prominence and reliability are
    different questions, and only the second one belongs in the word "strong".
    """
    resolved = holds + breaks
    # Unresolved (0.5) rather than 0 when nothing has resolved yet: no evidence
    # is not the same as evidence of weakness.
    hold_ratio = (holds / resolved) if resolved else 0.5

    parts = {
        "tests": min(tests / TESTS_SATURATE, 1.0),
        "recency": math.exp(-bars_since / RECENCY_HALFLIFE_BARS),
        "volume": min(volume_share / VOLUME_SATURATE, 1.0),
        "span": min(span / SPAN_SATURATE, 1.0),
    }
    # How much history sits at this price.
    prominence = sum(parts[k] * w for k, w in _PROMINENCE_WEIGHTS.items())
    if flipped:
        # Polarity flip is real corroboration: the level mattered to both sides.
        prominence = min(prominence + 0.05, 1.0)

    # How reliably it did its job. Floor at RELIABILITY_FLOOR so a level that
    # always breaks still registers as a price that matters — it just can't be
    # called strong.
    reliability = RELIABILITY_FLOOR + (1 - RELIABILITY_FLOOR) * hold_ratio

    parts["hold_ratio"] = hold_ratio
    parts["prominence"] = prominence
    parts["reliability"] = reliability
    return prominence * reliability, hold_ratio, parts


def _strength_of(score: float, hold_ratio: float, resolved: int) -> str:
    """
    Label with a hard reliability cap.

    The cap is the whole point: a level that breaks more often than it holds is
    not strong, however prominent it is. Scoring alone let those through, so the
    rule is stated explicitly rather than left to weights.
    """
    if score >= STRONG_MIN:
        label = "strong"
    elif score >= MEDIUM_MIN:
        label = "medium"
    else:
        label = "weak"

    # Only cap once there is a real record to judge — two resolved tests is thin
    # evidence, and capping on it would punish young levels for being young.
    if resolved >= MIN_RESOLVED_FOR_CAP:
        if hold_ratio < WEAK_HOLD_RATIO:
            return "weak"
        if hold_ratio < STRONG_HOLD_RATIO and label == "strong":
            return "medium"
    return label


def build_zones(
    df: pd.DataFrame,
    atr: float,
    price: Optional[float] = None,
    window: int = SWING_WINDOW,
) -> List[Zone]:
    """
    Full scored zone set for `df`, nearest-to-price ordering left to the caller.

    `atr` sets every distance in here (cluster tolerance, minimum band width) so
    the geometry adapts to the instrument's volatility instead of using a fixed
    percentage that is too tight for TPIA and too loose for BBCA.

    Floor-trader pivots are deliberately NOT included. They are arithmetic off a
    single bar, and mixing them into the swing set was inflating the very count
    that is supposed to measure how often price actually respected a level.
    """
    if atr <= 0 or not math.isfinite(atr) or len(df) < window * 2 + 2:
        return []

    pivots = find_swing_points(df, window)
    if not pivots:
        return []

    price = float(price if price is not None else df["Close"].iloc[-1])
    min_half = MIN_ZONE_ATR * atr / 2.0

    zones: List[Zone] = []
    for cluster in _cluster_pivots(pivots, atr):
        prices = [p[1] for p in cluster]
        lo, hi = min(prices), max(prices)
        mid = float(np.mean(prices))
        # Guarantee a band even for a lone pivot.
        if (hi - lo) < 2 * min_half:
            lo, hi = mid - min_half, mid + min_half

        kinds = {p[2] for p in cluster}
        flipped = len(kinds) > 1

        tests, holds, breaks, bars_since, span = _count_tests(df, lo, hi, atr)
        vol = _volume_share(df, lo, hi)
        score, hold_ratio, _ = _score_zone(
            tests, holds, breaks, bars_since, vol, span, flipped
        )

        zones.append(
            Zone(
                low=float(lo),
                high=float(hi),
                mid=float(mid),
                kind="support" if mid < price else "resistance",
                flipped=flipped,
                tests=tests,
                holds=holds,
                breaks=breaks,
                bars_since_test=bars_since,
                volume_share=float(vol),
                span_bars=span,
                score=float(score),
                strength=_strength_of(score, hold_ratio, holds + breaks),
            )
        )

    zones.sort(key=lambda z: z.mid)
    return zones


# ── Selection ────────────────────────────────────────────────────────────────


def nearest_zones(
    price: float, zones: Sequence[Zone]
) -> Tuple[Optional[Zone], Optional[Zone]]:
    """
    (support, resistance): the closest zone whose band sits fully below / above
    `price`. Either may be None — at an all-time high there is no resistance
    overhead, and saying so is more honest than inventing one.
    """
    below = [z for z in zones if z.high < price]
    above = [z for z in zones if z.low > price]
    return (
        max(below, key=lambda z: z.high) if below else None,
        min(above, key=lambda z: z.low) if above else None,
    )


def anchor_zone(
    price: float,
    zones: Sequence[Zone],
    side: str,
    min_strength: str = "medium",
    max_distance_atr: float = 4.0,
    atr: float = 0.0,
) -> Tuple[Optional[Zone], Optional[Zone]]:
    """
    Pick the zone a stop should hang off, and report what was nearest.

    Returns (anchor, nearest). `anchor` is the closest zone meeting
    `min_strength`; `nearest` is the closest zone of any strength. When they
    differ the caller should say so — "your stop is under the 4,180 shelf, not
    the 4,340 scribble just below price" is exactly the reasoning a user needs
    to see rather than a bare number.

    A qualifying zone further than `max_distance_atr` away is rejected: a stop
    anchored 8 ATR out is technically well-founded and practically useless, so
    we fall back to the ATR stop instead of pretending the distance is fine.
    """
    order = {"weak": 0, "medium": 1, "strong": 2}
    floor = order[min_strength]

    if side == "support":
        candidates = [z for z in zones if z.high < price]
        key = lambda z: z.high                      # noqa: E731
        pick = max
        distance = lambda z: price - z.high         # noqa: E731
    else:
        candidates = [z for z in zones if z.low > price]
        key = lambda z: z.low                       # noqa: E731
        pick = min
        distance = lambda z: z.low - price          # noqa: E731

    if not candidates:
        return None, None

    nearest = pick(candidates, key=key)
    qualified = [
        z for z in candidates
        if order[z.strength] >= floor
        and (atr <= 0 or distance(z) <= max_distance_atr * atr)
    ]
    anchor = pick(qualified, key=key) if qualified else None
    return anchor, nearest


def describe_zone(zone: Optional[Zone], fmt=None) -> str:
    """
    "4,180–4,240 · KUAT (6 tes · 5 bertahan · terakhir 12 bar lalu · 21% volume)"

    `fmt` formats a price (e.g. IDX tick rounding); defaults to thousands
    separators with no decimals.
    """
    if zone is None:
        return "—"
    f = fmt or (lambda v: f"{v:,.0f}")
    return f"{f(zone.low)}–{f(zone.high)} · {zone.label} ({zone.evidence()})"
