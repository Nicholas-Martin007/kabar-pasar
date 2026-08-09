"""
Classical chart-pattern recognition.

Detects 13 textbook formations from swing structure and least-squares
trendlines, scores each on how closely it matches the ideal geometry, and
returns only high-conformance instances.

    from ta_engine.pattern_detector import detect_patterns
    patterns = detect_patterns(df)          # df = OHLCV from Ticker().history()
    [p.to_dict() for p in patterns]

## What `quality_score` measures — read this before showing it to anyone

`quality_score` is a **geometric conformance score**: how closely the price
structure matches the textbook shape, given trendline fit (R²), the number of
confirmed touches on each boundary, proportion/symmetry checks, and volume
behaviour. Range 0.0–1.0.

It is **NOT a probability that the trade will work.** A 0.88 means "this is a
textbook-clean descending triangle", not "88% of these go on to hit target".
Published success rates for classical patterns are far lower and heavily
dependent on how "success" is defined; the academic evidence for their
predictive power is mixed at best (Lo, Mamaysky & Wang 2000). Anything that
surfaces this number to a user must label it as shape quality, never as
confidence, win rate, or probability.

## Geometry conventions

* Slopes are normalised as **total fractional change across the pattern span**
  (`slope * bars / mean_price`), so thresholds mean the same thing on a Rp50
  small-cap and a Rp10,000 blue chip.
* A boundary is "flat" when |normalised slope| <= `FLAT_SLOPE_TOL`.
* Only **confirmed** pivots are used — a swing needs `lookback` bars on both
  sides, so the newest bars intentionally contribute no pivots. This is what
  stops the detector inventing a pattern that evaporates on the next candle.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Tunables ─────────────────────────────────────────────────────────────────

# Bars required either side of a swing for it to count as a confirmed pivot.
DEFAULT_LOOKBACK = 3
# Minimum move between consecutive alternating pivots, as a fraction of price.
# Filters out micro-zigzag that would otherwise fit "patterns" into noise.
DEFAULT_NOISE_TOL = 0.015
# |normalised slope| at or below this counts as horizontal.
FLAT_SLOPE_TOL = 0.02
# A pivot counts as "touching" a trendline within this fraction of price.
TOUCH_TOL = 0.02
# Boundaries must narrow by at least this fraction to count as converging.
MIN_CONVERGENCE = 0.20
# Only patterns at or above this score are returned.
MIN_QUALITY = 0.80
# A pattern is only a *setup* while its breakout is still ahead or very recent.
# Without this the scanner reports textbook shapes that completed months ago —
# measured over the IDX large caps, median detection age was 108 bars (~5
# months), i.e. trades that already resolved one way or the other.
MAX_AGE_BARS = 25

# Reversal patterns, per the standard taxonomy. Wedges are classified as
# reversals here (a rising wedge most often resolves down); in practice they
# also appear as continuations against the prevailing trend.
_REVERSAL_TYPES = {
    "Double Top",
    "Double Bottom",
    "Head and Shoulders",
    "Inverse Head and Shoulders",
    "Rising Wedge",
    "Falling Wedge",
}


# ── Data structures ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Pivot:
    """A confirmed swing point."""

    idx: int  # positional index into the source frame
    ts: pd.Timestamp
    price: float
    kind: str  # "high" | "low"


@dataclass
class TrendLine:
    """Least-squares line through a set of pivots, in (bar index, price) space."""

    slope: float  # price units per bar
    intercept: float  # price at bar index 0
    r2: float
    touches: int
    norm_slope: float  # fractional price change across the fitted span

    def value_at(self, x: float) -> float:
        return self.slope * x + self.intercept


@dataclass
class Pattern:
    pattern_type: str
    quality_score: float
    is_reversal: bool
    lines: List[List[Tuple[datetime, float]]]
    key_levels: Dict[str, float]
    # Context beyond the required contract — useful for charting and audit.
    direction: str  # "bullish" | "bearish"
    start_ts: datetime
    end_ts: datetime
    start_idx: int
    end_idx: int
    volume_confirmed: bool
    score_breakdown: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── Pivot extraction ─────────────────────────────────────────────────────────


def find_pivots(
    df: pd.DataFrame,
    lookback: int = DEFAULT_LOOKBACK,
    noise_tol: float = DEFAULT_NOISE_TOL,
) -> List[Pivot]:
    """
    Confirmed fractal swing points, newest last.

    A bar is a pivot high when its High is the max across +/- `lookback` bars
    (mirrored for lows). The final `lookback` bars are excluded because their
    pivot status is not yet decided.

    `noise_tol` then drops alternating pivots whose move is smaller than that
    fraction of price, collapsing micro-zigzag. Without it, trendline fits latch
    onto noise and every chart "contains" a triangle.
    """
    highs = df["High"].to_numpy(dtype=float)
    lows = df["Low"].to_numpy(dtype=float)
    n = len(df)
    if n < 2 * lookback + 1:
        return []

    raw: List[Pivot] = []
    for i in range(lookback, n - lookback):
        window_h = highs[i - lookback : i + lookback + 1]
        window_l = lows[i - lookback : i + lookback + 1]
        if highs[i] == window_h.max():
            raw.append(Pivot(i, df.index[i], float(highs[i]), "high"))
        if lows[i] == window_l.min():
            raw.append(Pivot(i, df.index[i], float(lows[i]), "low"))

    raw.sort(key=lambda p: (p.idx, 0 if p.kind == "high" else 1))
    return _filter_noise(raw, noise_tol)


def _filter_noise(pivots: List[Pivot], noise_tol: float) -> List[Pivot]:
    """
    Enforce alternation and a minimum swing size.

    Consecutive same-kind pivots collapse to the more extreme one (the higher
    high / lower low). Alternating pairs closer than `noise_tol` are dropped.
    """
    if not pivots:
        return pivots

    out: List[Pivot] = []
    for p in pivots:
        if not out:
            out.append(p)
            continue
        last = out[-1]
        if p.kind == last.kind:
            # Keep whichever is the true extreme of the two. This alternation
            # pass runs even when noise_tol is 0: downstream detectors pair
            # pivots positionally (peak, trough, peak), so a run of same-kind
            # pivots would silently misalign every double top and H&S.
            better = (p.price > last.price) if p.kind == "high" else (p.price < last.price)
            if better:
                out[-1] = p
            continue
        if noise_tol > 0:
            ref = max(abs(last.price), 1e-9)
            if abs(p.price - last.price) / ref < noise_tol:
                continue  # swing too small to be structure
        out.append(p)
    return out


# ── Line fitting ─────────────────────────────────────────────────────────────


def fit_line(xs: Sequence[float], ys: Sequence[float]) -> Tuple[float, float, float]:
    """
    Least-squares fit -> (slope, intercept, r2).

    r2 is 1.0 for a 2-point fit (a line through two points is exact) and 1.0 for
    a perfectly flat series, where the usual formula is 0/0.
    """
    x = np.asarray(xs, dtype=float)
    y = np.asarray(ys, dtype=float)
    if len(x) < 2:
        return 0.0, float(y[0]) if len(y) else 0.0, 0.0

    slope, intercept = np.polyfit(x, y, 1)
    pred = slope * x + intercept
    ss_res = float(np.sum((y - pred) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    if ss_tot <= 1e-12:
        r2 = 1.0  # constant series — a flat line fits it exactly
    else:
        r2 = max(0.0, 1.0 - ss_res / ss_tot)
    return float(slope), float(intercept), float(r2)


def build_trendline(pivots: Sequence[Pivot], all_same_kind: Sequence[Pivot]) -> TrendLine:
    """Fit a line to `pivots` and count how many of `all_same_kind` touch it."""
    xs = [p.idx for p in pivots]
    ys = [p.price for p in pivots]
    slope, intercept, r2 = fit_line(xs, ys)

    mean_price = float(np.mean(ys)) if ys else 1.0
    span = max(1, max(xs) - min(xs)) if xs else 1
    norm_slope = (slope * span) / max(abs(mean_price), 1e-9)

    touches = 0
    for p in all_same_kind:
        expected = slope * p.idx + intercept
        if abs(p.price - expected) / max(abs(expected), 1e-9) <= TOUCH_TOL:
            touches += 1

    return TrendLine(
        slope=slope,
        intercept=intercept,
        r2=r2,
        touches=touches,
        norm_slope=norm_slope,
    )


# ── Volume confirmation ──────────────────────────────────────────────────────


def volume_confirmation(
    df: pd.DataFrame,
    consolidation: Tuple[int, int],
    pole: Optional[Tuple[int, int]] = None,
) -> Dict[str, Any]:
    """
    Textbook volume behaviour: heavy on the impulse, drying up through the
    consolidation.

    Returns the raw measurements plus a 0..1 `score`, so the caller can both
    grade the pattern and explain the grade.
    """
    vol = df["Volume"].to_numpy(dtype=float)
    c0, c1 = consolidation
    c0, c1 = max(0, c0), min(len(vol) - 1, c1)
    if c1 <= c0:
        return {"score": 0.0, "declining": False, "pole_ratio": None, "slope": 0.0}

    seg = vol[c0 : c1 + 1]
    if seg.size < 3 or not np.isfinite(seg).all() or seg.mean() <= 0:
        return {"score": 0.0, "declining": False, "pole_ratio": None, "slope": 0.0}

    # Normalised regression slope across the consolidation: negative = drying up.
    xs = np.arange(seg.size, dtype=float)
    slope, _, _ = fit_line(xs, seg)
    norm_slope = (slope * seg.size) / max(seg.mean(), 1e-9)
    declining = norm_slope < -0.05

    score = 0.0
    # Up to 0.6 for the consolidation drying up, saturating at a 60% decline.
    if declining:
        score += 0.6 * min(1.0, abs(norm_slope) / 0.6)

    pole_ratio: Optional[float] = None
    if pole is not None:
        p0, p1 = max(0, pole[0]), min(len(vol) - 1, pole[1])
        if p1 > p0:
            pole_seg = vol[p0 : p1 + 1]
            if pole_seg.size and pole_seg.mean() > 0 and seg.mean() > 0:
                pole_ratio = float(pole_seg.mean() / seg.mean())
                # Up to 0.4 for pole volume exceeding consolidation volume.
                if pole_ratio > 1.0:
                    score += 0.4 * min(1.0, (pole_ratio - 1.0) / 0.5)
    else:
        # No pole to compare against (triangles): rescale so a perfectly drying
        # consolidation can still reach 1.0 rather than being capped at 0.6.
        score = min(1.0, score / 0.6)

    return {
        "score": round(min(1.0, score), 4),
        "declining": bool(declining),
        "pole_ratio": round(pole_ratio, 4) if pole_ratio is not None else None,
        "slope": round(float(norm_slope), 4),
    }


# ── Scoring helpers ──────────────────────────────────────────────────────────


def _touch_score(upper_touches: int, lower_touches: int) -> float:
    """
    Touch quality. Two touches per boundary is the minimum that defines a line
    at all; three or more is what makes it meaningful, so the score is built to
    require 3+ on both sides to approach 1.0.
    """
    if upper_touches < 2 or lower_touches < 2:
        return 0.0
    per = [min(1.0, (t - 2) / 2.0 * 0.5 + 0.5) for t in (upper_touches, lower_touches)]
    return float(np.mean(per))


def _slope_score(actual: float, ideal: float, tolerance: float) -> float:
    """1.0 when the normalised slope matches `ideal`, decaying to 0 at `tolerance`."""
    return float(max(0.0, 1.0 - abs(actual - ideal) / max(tolerance, 1e-9)))


def _combine(parts: Dict[str, float], weights: Dict[str, float]) -> float:
    total_w = sum(weights.values())
    if total_w <= 0:
        return 0.0
    return float(sum(parts.get(k, 0.0) * w for k, w in weights.items()) / total_w)


def _segment(line: TrendLine, x0: int, x1: int, index: pd.Index) -> List[Tuple[datetime, float]]:
    """Two endpoints of a fitted line, as (datetime, price) for plotting."""
    return [
        (_to_dt(index[x0]), float(line.value_at(x0))),
        (_to_dt(index[x1]), float(line.value_at(x1))),
    ]


def _to_dt(ts: Any) -> datetime:
    if isinstance(ts, pd.Timestamp):
        return ts.to_pydatetime()
    return ts


# ── Triangle / wedge family ──────────────────────────────────────────────────


def _classify_converging(
    upper: TrendLine, lower: TrendLine
) -> Optional[Tuple[str, str]]:
    """
    Map a pair of boundary slopes to a pattern name + direction.

    Returns None when the shape is a channel or otherwise not one of the
    converging formations we claim to recognise.
    """
    up, lo = upper.norm_slope, lower.norm_slope
    up_flat = abs(up) <= FLAT_SLOPE_TOL
    lo_flat = abs(lo) <= FLAT_SLOPE_TOL

    if up_flat and lo > FLAT_SLOPE_TOL:
        return "Ascending Triangle", "bullish"
    if lo_flat and up < -FLAT_SLOPE_TOL:
        return "Descending Triangle", "bearish"
    if up < -FLAT_SLOPE_TOL and lo > FLAT_SLOPE_TOL:
        return "Symmetrical Triangle", "neutral"
    # Both boundaries sloping the same way and converging = wedge.
    if up > FLAT_SLOPE_TOL and lo > FLAT_SLOPE_TOL and lo > up:
        return "Rising Wedge", "bearish"
    if up < -FLAT_SLOPE_TOL and lo < -FLAT_SLOPE_TOL and up < lo:
        return "Falling Wedge", "bullish"
    return None


def _detect_converging(
    df: pd.DataFrame, pivots: List[Pivot], window: Tuple[int, int]
) -> Optional[Pattern]:
    """Fit both boundaries over `window` and classify triangles / wedges."""
    x0, x1 = window
    highs = [p for p in pivots if p.kind == "high" and x0 <= p.idx <= x1]
    lows = [p for p in pivots if p.kind == "low" and x0 <= p.idx <= x1]
    if len(highs) < 2 or len(lows) < 2:
        return None

    upper = build_trendline(highs, highs)
    lower = build_trendline(lows, lows)

    width_start = upper.value_at(x0) - lower.value_at(x0)
    width_end = upper.value_at(x1) - lower.value_at(x1)
    if width_start <= 0:
        # Boundaries already inverted where the pattern begins — the fit is
        # meaningless, not merely late-stage.
        return None

    # `x_eff` is where we read the breakout/stop levels. Converging boundaries
    # meet at an apex, and if that apex falls inside the window the lines cross
    # and width goes negative. That is the pattern maturing, not a malformed
    # one — price simply ran to the apex without resolving. Back the read-off
    # point up to just before the crossing so the quoted levels stay ordered.
    x_eff = x1
    if width_end <= 0:
        denom = upper.slope - lower.slope
        if denom == 0:
            return None
        x_apex = (lower.intercept - upper.intercept) / denom
        x_eff = int(np.floor(x_apex)) - 1
        if x_eff <= x0:
            return None  # apex sits at/before the start — nothing to measure
        convergence = 1.0
    else:
        convergence = 1.0 - (width_end / width_start)

    if convergence < MIN_CONVERGENCE:
        return None

    classified = _classify_converging(upper, lower)
    if classified is None:
        return None
    name, direction = classified

    vol = volume_confirmation(df, consolidation=(x0, x1))

    # Geometry: how well both boundaries fit, plus how cleanly they converge.
    geometry = float(np.mean([upper.r2, lower.r2])) * 0.7 + min(1.0, convergence / 0.6) * 0.3
    touches = _touch_score(upper.touches, lower.touches)

    parts = {"geometry": geometry, "touches": touches, "volume": vol["score"]}
    score = _combine(parts, {"geometry": 0.45, "touches": 0.35, "volume": 0.20})

    key_levels = _converging_levels(name, upper, lower, x0, x_eff, width_start)
    if key_levels is None:
        return None

    # Draw each boundary across the pivots that actually define it, not the
    # whole scan window. Extending the fit back to x0 extrapolates past the
    # first touch and can run the line clean off the bottom of the chart.
    draw_start = min(highs[0].idx, lows[0].idx)
    draw_end = min(x1, max(x_eff, max(highs[-1].idx, lows[-1].idx)))
    if draw_end <= draw_start:
        return None

    return Pattern(
        pattern_type=name,
        quality_score=round(score, 4),
        is_reversal=name in _REVERSAL_TYPES,
        lines=[
            _segment(upper, draw_start, draw_end, df.index),
            _segment(lower, draw_start, draw_end, df.index),
        ],
        key_levels=key_levels,
        direction=direction,
        start_ts=_to_dt(df.index[draw_start]),
        end_ts=_to_dt(df.index[draw_end]),
        start_idx=draw_start,
        end_idx=draw_end,
        volume_confirmed=bool(vol["declining"]),
        score_breakdown={k: round(v, 4) for k, v in parts.items()},
    )


def _converging_levels(
    name: str,
    upper: TrendLine,
    lower: TrendLine,
    x0: int,
    x1: int,
    height: float,
) -> Optional[Dict[str, float]]:
    """
    Breakout level, measured-move target and stop for a converging pattern.

    The classic measured move projects the pattern's height at its widest point
    from the breakout level.
    """
    up_end = upper.value_at(x1)
    lo_end = lower.value_at(x1)

    bearish = name in ("Descending Triangle", "Rising Wedge")
    if name == "Symmetrical Triangle":
        # Direction is genuinely undecided until it breaks; quote the upside
        # resolution and let `direction: neutral` carry the ambiguity.
        breakout, target, stop = up_end, up_end + height, lo_end
    elif bearish:
        breakout, target, stop = lo_end, lo_end - height, up_end
    else:
        breakout, target, stop = up_end, up_end + height, lo_end

    if not all(np.isfinite(v) for v in (breakout, target, stop)):
        return None
    return {
        "breakout_level": round(float(breakout), 4),
        "target": round(float(target), 4),
        "stop_loss": round(float(stop), 4),
    }


# ── Flag / pennant family ────────────────────────────────────────────────────


def _detect_flag_pennant(
    df: pd.DataFrame,
    pivots: List[Pivot],
    atr: float,
    min_pole_atr: float = 3.0,
    max_consolidation: int = 30,
) -> List[Pattern]:
    """
    Pole + consolidation.

    The pole is a sharp directional thrust (>= `min_pole_atr` ATR); the
    consolidation that follows is a flag when its boundaries are roughly
    parallel and a pennant when they converge. Volume should be heavy on the
    pole and drying through the consolidation — that contrast is most of what
    separates these from ordinary chop.
    """
    out: List[Pattern] = []
    close = df["Close"].to_numpy(dtype=float)
    n = len(df)
    if n < 25 or atr <= 0:
        return out

    for pole_len in (5, 8, 12):
        for cons_len in (8, 12, 18, 25):
            if cons_len > max_consolidation:
                continue
            c1 = n - 1
            c0 = c1 - cons_len
            p1 = c0
            p0 = p1 - pole_len
            if p0 < 0:
                continue

            move = close[p1] - close[p0]
            if abs(move) < min_pole_atr * atr:
                continue
            bullish = move > 0

            highs = [p for p in pivots if p.kind == "high" and c0 <= p.idx <= c1]
            lows = [p for p in pivots if p.kind == "low" and c0 <= p.idx <= c1]
            if len(highs) < 2 or len(lows) < 2:
                continue

            upper = build_trendline(highs, highs)
            lower = build_trendline(lows, lows)

            w0 = upper.value_at(c0) - lower.value_at(c0)
            w1 = upper.value_at(c1) - lower.value_at(c1)
            if w0 <= 0 or w1 <= 0:
                continue
            convergence = 1.0 - (w1 / w0)

            # A flag drifts against the pole in a parallel channel; a pennant
            # coils into a small symmetrical triangle.
            parallel = abs(upper.norm_slope - lower.norm_slope) < 0.03
            converging = convergence >= MIN_CONVERGENCE

            if converging:
                kind = "Pennant"
                shape_score = min(1.0, convergence / 0.6)
            elif parallel:
                kind = "Flag"
                # A flag should lean against the pole, or at worst run flat.
                drift = upper.norm_slope
                counter = (drift < FLAT_SLOPE_TOL) if bullish else (drift > -FLAT_SLOPE_TOL)
                if not counter:
                    continue
                shape_score = 1.0 - min(1.0, abs(upper.norm_slope - lower.norm_slope) / 0.03)
            else:
                continue

            name = f"{'Bull' if bullish else 'Bear'} {kind}"
            vol = volume_confirmation(df, consolidation=(c0, c1), pole=(p0, p1))

            geometry = float(np.mean([upper.r2, lower.r2])) * 0.6 + shape_score * 0.4
            touches = _touch_score(upper.touches, lower.touches)
            parts = {"geometry": geometry, "touches": touches, "volume": vol["score"]}
            # Volume carries more weight here: the pole/consolidation contrast
            # is the defining feature, not an optional confirmation.
            score = _combine(parts, {"geometry": 0.40, "touches": 0.30, "volume": 0.30})

            pole_height = abs(move)
            if bullish:
                breakout = upper.value_at(c1)
                target = breakout + pole_height
                stop = lower.value_at(c1)
            else:
                breakout = lower.value_at(c1)
                target = breakout - pole_height
                stop = upper.value_at(c1)

            if not all(np.isfinite(v) for v in (breakout, target, stop)):
                continue

            out.append(
                Pattern(
                    pattern_type=name,
                    quality_score=round(score, 4),
                    is_reversal=False,
                    lines=[
                        _segment(upper, c0, c1, df.index),
                        _segment(lower, c0, c1, df.index),
                    ],
                    key_levels={
                        "breakout_level": round(float(breakout), 4),
                        "target": round(float(target), 4),
                        "stop_loss": round(float(stop), 4),
                    },
                    direction="bullish" if bullish else "bearish",
                    start_ts=_to_dt(df.index[p0]),
                    end_ts=_to_dt(df.index[c1]),
                    start_idx=p0,
                    end_idx=c1,
                    volume_confirmed=bool(vol["declining"]),
                    score_breakdown={k: round(v, 4) for k, v in parts.items()},
                )
            )
    return out


# ── Double top / bottom ──────────────────────────────────────────────────────


def _second_test_volume(df: pd.DataFrame, first_idx: int, second_idx: int, span: int = 3) -> float:
    """
    Score the classic "second test on lighter volume" tell, 0..1.

    A double top whose second peak trades as heavily as the first shows demand
    still present; the lighter retest is what makes the pattern meaningful.
    Returns 0.5 (neutral) when volume is unusable rather than rewarding or
    punishing on missing data.
    """
    vol = df["Volume"].to_numpy(dtype=float)
    n = len(vol)

    def around(i: int) -> float:
        lo, hi = max(0, i - span), min(n - 1, i + span)
        seg = vol[lo : hi + 1]
        return float(seg.mean()) if seg.size and np.isfinite(seg).all() else float("nan")

    v1, v2 = around(first_idx), around(second_idx)
    if not (np.isfinite(v1) and np.isfinite(v2)) or v1 <= 0:
        return 0.5
    ratio = v2 / v1
    if ratio >= 1.0:
        return 0.0  # second test as heavy or heavier — no confirmation
    # Saturate at a 40% drop in volume on the retest.
    return float(min(1.0, (1.0 - ratio) / 0.4))


def _detect_double(
    df: pd.DataFrame, pivots: List[Pivot], tolerance: float = 0.03
) -> List[Pattern]:
    """
    Two peaks (or troughs) at a similar level separated by a counter-swing.

    The neckline is the intervening extreme; the measured move projects the
    pattern height from that neckline.
    """
    out: List[Pattern] = []

    for kind, name, direction in (
        ("high", "Double Top", "bearish"),
        ("low", "Double Bottom", "bullish"),
    ):
        same = [p for p in pivots if p.kind == kind]
        for a, b in zip(same, same[1:]):
            mids = [p for p in pivots if a.idx < p.idx < b.idx and p.kind != kind]
            if not mids:
                continue
            # The deepest counter-swing between the two extremes is the neckline.
            mid = (min(mids, key=lambda p: p.price) if kind == "high"
                   else max(mids, key=lambda p: p.price))

            ref = max(abs(a.price), 1e-9)
            level_diff = abs(a.price - b.price) / ref
            if level_diff > tolerance:
                continue  # peaks too unequal to be a double

            height = abs(((a.price + b.price) / 2.0) - mid.price)
            if height <= 0 or height / ref < 0.03:
                continue  # too shallow to be structure

            span = b.idx - a.idx
            if span < 5:
                continue  # peaks too close together

            # Equality of the two extremes is the defining trait.
            equality = 1.0 - min(1.0, level_diff / tolerance)
            # Depth relative to price: a deeper retrace is a cleaner pattern.
            depth = min(1.0, (height / ref) / 0.10)
            # Rough time symmetry between the two halves.
            left, right = mid.idx - a.idx, b.idx - mid.idx
            symmetry = 1.0 - min(1.0, abs(left - right) / max(left + right, 1))
            # Classic confirmation: the second extreme forms on lighter volume
            # than the first — demand (or supply) failing to follow through.
            # Without this these patterns are graded far more leniently than
            # triangles, which must also satisfy fit and touch counts.
            vol_score = _second_test_volume(df, a.idx, b.idx)

            parts = {
                "equality": equality,
                "depth": depth,
                "symmetry": symmetry,
                "volume": vol_score,
            }
            score = _combine(
                parts,
                {"equality": 0.35, "depth": 0.20, "symmetry": 0.20, "volume": 0.25},
            )

            neckline = mid.price
            if kind == "high":
                breakout, target, stop = neckline, neckline - height, max(a.price, b.price)
            else:
                breakout, target, stop = neckline, neckline + height, min(a.price, b.price)

            out.append(
                Pattern(
                    pattern_type=name,
                    quality_score=round(score, 4),
                    is_reversal=True,
                    lines=[
                        # Neckline, then the line joining the two extremes.
                        [(_to_dt(a.ts), neckline), (_to_dt(b.ts), neckline)],
                        [(_to_dt(a.ts), a.price), (_to_dt(b.ts), b.price)],
                    ],
                    key_levels={
                        "breakout_level": round(float(breakout), 4),
                        "target": round(float(target), 4),
                        "stop_loss": round(float(stop), 4),
                    },
                    direction=direction,
                    start_ts=_to_dt(a.ts),
                    end_ts=_to_dt(b.ts),
                    start_idx=a.idx,
                    end_idx=b.idx,
                    volume_confirmed=vol_score >= 0.5,
                    score_breakdown={k: round(v, 4) for k, v in parts.items()},
                )
            )
    return out


# ── Head and shoulders ───────────────────────────────────────────────────────


def _detect_head_shoulders(
    df: pd.DataFrame, pivots: List[Pivot], shoulder_tol: float = 0.05
) -> List[Pattern]:
    """
    Three extremes where the middle one dominates and the outer two are roughly
    level, with the neckline drawn through the two intervening counter-swings.
    """
    out: List[Pattern] = []

    for kind, name, direction in (
        ("high", "Head and Shoulders", "bearish"),
        ("low", "Inverse Head and Shoulders", "bullish"),
    ):
        same = [p for p in pivots if p.kind == kind]
        for ls, head, rs in zip(same, same[1:], same[2:]):
            if kind == "high":
                dominant = head.price > ls.price and head.price > rs.price
            else:
                dominant = head.price < ls.price and head.price < rs.price
            if not dominant:
                continue

            ref = max(abs(head.price), 1e-9)
            shoulder_diff = abs(ls.price - rs.price) / ref
            if shoulder_diff > shoulder_tol:
                continue

            # Neckline through the two counter-swings bracketing the head.
            left_mids = [p for p in pivots if ls.idx < p.idx < head.idx and p.kind != kind]
            right_mids = [p for p in pivots if head.idx < p.idx < rs.idx and p.kind != kind]
            if not left_mids or not right_mids:
                continue
            if kind == "high":
                lm = min(left_mids, key=lambda p: p.price)
                rm = min(right_mids, key=lambda p: p.price)
            else:
                lm = max(left_mids, key=lambda p: p.price)
                rm = max(right_mids, key=lambda p: p.price)

            neck_slope, neck_intercept, _ = fit_line([lm.idx, rm.idx], [lm.price, rm.price])
            neck_at_rs = neck_slope * rs.idx + neck_intercept
            height = abs(head.price - (neck_slope * head.idx + neck_intercept))
            if height / ref < 0.03:
                continue

            # The head must clear both shoulders by a visible margin, or this is
            # just three similar peaks.
            prominence = abs(head.price - max(ls.price, rs.price)) if kind == "high" \
                else abs(min(ls.price, rs.price) - head.price)
            prominence_score = min(1.0, (prominence / ref) / 0.05)
            shoulder_score = 1.0 - min(1.0, shoulder_diff / shoulder_tol)
            left_span, right_span = head.idx - ls.idx, rs.idx - head.idx
            symmetry = 1.0 - min(1.0, abs(left_span - right_span) / max(left_span + right_span, 1))

            # Textbook H&S shows volume fading across the formation: heaviest on
            # the left shoulder, lighter into the head, lightest on the right.
            # Held to the same standard as the triangles rather than scored on
            # geometry alone.
            vol_score = _second_test_volume(df, ls.idx, rs.idx)

            parts = {
                "shoulders": shoulder_score,
                "prominence": prominence_score,
                "symmetry": symmetry,
                "volume": vol_score,
            }
            score = _combine(
                parts,
                {"shoulders": 0.30, "prominence": 0.25, "symmetry": 0.20, "volume": 0.25},
            )

            if kind == "high":
                target, stop = neck_at_rs - height, max(ls.price, rs.price)
            else:
                target, stop = neck_at_rs + height, min(ls.price, rs.price)

            if not all(np.isfinite(v) for v in (neck_at_rs, target, stop)):
                continue

            out.append(
                Pattern(
                    pattern_type=name,
                    quality_score=round(score, 4),
                    is_reversal=True,
                    lines=[
                        # Neckline extended across the formation.
                        [
                            (_to_dt(ls.ts), float(neck_slope * ls.idx + neck_intercept)),
                            (_to_dt(rs.ts), float(neck_at_rs)),
                        ],
                        # Shoulder-head-shoulder outline.
                        [(_to_dt(ls.ts), ls.price), (_to_dt(head.ts), head.price)],
                        [(_to_dt(head.ts), head.price), (_to_dt(rs.ts), rs.price)],
                    ],
                    key_levels={
                        "breakout_level": round(float(neck_at_rs), 4),
                        "target": round(float(target), 4),
                        "stop_loss": round(float(stop), 4),
                    },
                    direction=direction,
                    start_ts=_to_dt(ls.ts),
                    end_ts=_to_dt(rs.ts),
                    start_idx=ls.idx,
                    end_idx=rs.idx,
                    volume_confirmed=vol_score >= 0.5,
                    score_breakdown={k: round(v, 4) for k, v in parts.items()},
                )
            )
    return out


# ── Public entry point ───────────────────────────────────────────────────────


def detect_patterns(
    df: pd.DataFrame,
    lookback: int = DEFAULT_LOOKBACK,
    noise_tol: float = DEFAULT_NOISE_TOL,
    min_quality: float = MIN_QUALITY,
    atr: Optional[float] = None,
    max_age_bars: int = MAX_AGE_BARS,
) -> List[Pattern]:
    """
    Scan `df` for all supported patterns and return those scoring at or above
    `min_quality`, best first.

    Args:
        df: OHLCV frame from `Ticker().history()` (flat columns, date index).
        lookback: bars either side required to confirm a swing pivot.
        noise_tol: minimum swing size, as a fraction of price.
        min_quality: geometric-conformance floor. Default 0.80 is strict — an
            empty list is the normal, honest result for most charts on most
            days. See the module docstring on what this score does and does not
            mean.
        atr: current ATR, used to size the flag/pennant pole. Derived from the
            frame when omitted.
        max_age_bars: how recently the pattern must have completed to still
            count as a setup. A textbook shape from five months ago has already
            resolved; reporting it as actionable is the single biggest source of
            false signal in a scanner like this.

    Returns:
        Patterns sorted by quality_score descending, de-duplicated so
        overlapping detections of the same type collapse to the best instance.
    """
    required = 2 * lookback + 10
    if len(df) < required:
        logger.debug("patterns.too_short bars=%d required=%d", len(df), required)
        return []

    pivots = find_pivots(df, lookback=lookback, noise_tol=noise_tol)
    # A double top is peak-trough-peak: three confirmed pivots is the genuine
    # floor for any pattern here, not four.
    if len(pivots) < 3:
        return []

    if atr is None:
        atr = _fallback_atr(df)

    found: List[Pattern] = []

    # Converging formations: scan several trailing windows so both a tight
    # 30-bar coil and a broad 90-bar triangle can surface.
    n = len(df)
    for span in (30, 45, 60, 90, 120):
        x1 = n - 1
        x0 = x1 - span
        if x0 < 0:
            continue
        p = _detect_converging(df, pivots, (x0, x1))
        if p is not None:
            found.append(p)

    found.extend(_detect_flag_pennant(df, pivots, atr))
    found.extend(_detect_double(df, pivots))
    found.extend(_detect_head_shoulders(df, pivots))

    last_idx = len(df) - 1
    # Drop patterns whose breakout is already history — see MAX_AGE_BARS.
    fresh = [p for p in found if (last_idx - p.end_idx) <= max_age_bars]
    qualified = [p for p in fresh if p.quality_score >= min_quality]
    qualified.sort(key=lambda p: -p.quality_score)
    deduped = _dedupe(qualified)

    logger.info(
        "patterns.scan bars=%d pivots=%d candidates=%d fresh=%d passed=%d "
        "(min_quality=%.2f max_age=%d)",
        len(df), len(pivots), len(found), len(fresh), len(deduped),
        min_quality, max_age_bars,
    )
    return deduped


def _fallback_atr(df: pd.DataFrame, window: int = 14) -> float:
    """Simple ATR for callers that didn't supply one."""
    high, low, close = df["High"], df["Low"], df["Close"]
    prev = close.shift()
    tr = pd.concat(
        [high - low, (high - prev).abs(), (low - prev).abs()], axis=1
    ).max(axis=1)
    val = float(tr.rolling(window).mean().iloc[-1])
    return val if np.isfinite(val) and val > 0 else 0.0


def _dedupe(patterns: List[Pattern]) -> List[Pattern]:
    """
    Keep the best instance per pattern type, and drop any pattern whose span is
    largely contained in a higher-scoring one — multi-window scanning otherwise
    reports the same triangle three times.
    """
    kept: List[Pattern] = []
    seen_types: set = set()
    for p in patterns:  # already sorted best-first
        if p.pattern_type in seen_types:
            continue
        overlapping = False
        for k in kept:
            lo = max(p.start_idx, k.start_idx)
            hi = min(p.end_idx, k.end_idx)
            inter = max(0, hi - lo)
            own = max(1, p.end_idx - p.start_idx)
            if inter / own > 0.7:
                overlapping = True
                break
        if overlapping:
            continue
        kept.append(p)
        seen_types.add(p.pattern_type)
    return kept


# ── Compact summary adapter ──────────────────────────────────────────────────

# Plot colours by direction, for callers that draw the trendlines themselves.
_SUMMARY_COLORS = {"bullish": "cyan", "bearish": "magenta", "neutral": "violet"}


def detect_pattern_summary(
    df: pd.DataFrame,
    min_quality: float = MIN_QUALITY,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Single best pattern in a flat, draw-ready dict.

    A convenience wrapper over `detect_patterns` for callers that want one
    answer and pre-formatted line coordinates rather than the full object list:

        {
          "detected": True,
          "pattern_type": "Ascending Triangle",
          "trendlines": [{"x1": ts, "y1": 4102.3, "x2": ts, "y2": 4498.2,
                          "color": "cyan", "style": "--"}, ...],
          "confidence": 0.87,
        }

    `confidence` is the same number as `quality_score` — geometric conformance,
    NOT a probability of the pattern playing out. The key is named this way to
    match the requested contract; the module docstring explains why the
    distinction matters before showing it to anyone.

    When nothing qualifies, returns `detected: False` with `pattern_type: None`
    and an empty `trendlines` list, so a caller can fall straight through to
    drawing plain support/resistance without special-casing.
    """
    patterns = detect_patterns(df, min_quality=min_quality, **kwargs)
    if not patterns:
        return {
            "detected": False,
            "pattern_type": None,
            "trendlines": [],
            "confidence": 0.0,
        }

    best = patterns[0]
    color = _SUMMARY_COLORS.get(best.direction, "cyan")
    trendlines = [
        {
            "x1": seg[0][0],
            "y1": seg[0][1],
            "x2": seg[-1][0],
            "y2": seg[-1][1],
            "color": color,
            "style": "--",
        }
        for seg in best.lines
    ]
    return {
        "detected": True,
        "pattern_type": best.pattern_type,
        "trendlines": trendlines,
        "confidence": best.quality_score,
        # Extras beyond the requested contract — additive, so a consumer reading
        # only the four documented keys is unaffected.
        "is_reversal": best.is_reversal,
        "direction": best.direction,
        "key_levels": best.key_levels,
    }


# ── RSI divergence ───────────────────────────────────────────────────────────

# Pivots closer together than this can't form a meaningful divergence — the two
# legs need to be distinct swings, not adjacent noise.
_DIV_MIN_BARS = 8
# Beyond this the two swings belong to different market phases and pairing them
# says nothing about current momentum.
_DIV_MAX_BARS = 60
# RSI must differ by at least this much for the divergence to be real rather
# than rounding.
_DIV_MIN_RSI_GAP = 3.0


def detect_rsi_divergence(
    df: pd.DataFrame, lookback: int = 90, rsi_col: str = "rsi14"
) -> Optional[Dict[str, Any]]:
    """
    Classic momentum divergence between price and RSI.

    Bearish: price prints a HIGHER high while RSI prints a LOWER high — the
    move is being made on weakening momentum. Bullish is the mirror on lows.

    Uses the same confirmed pivots as the pattern engine, so a divergence never
    rests on an unconfirmed swing that the next candle erases. Returns the most
    recent qualifying instance, or None.

    This is an exhaustion *warning*, not a reversal signal: divergence can
    persist for a long time in a strong trend, and price is the thing that
    ultimately confirms or refutes it.
    """
    if rsi_col not in df.columns or len(df) < 30:
        return None

    window = df.tail(lookback)
    pivots = find_pivots(window)
    if len(pivots) < 4:
        return None

    rsi = window[rsi_col]
    idx_of = {p.idx: p for p in pivots}

    def rsi_at(pos: int) -> Optional[float]:
        try:
            v = float(rsi.iloc[pos])
            return v if np.isfinite(v) else None
        except Exception:
            return None

    best: Optional[Dict[str, Any]] = None
    for kind, name, direction in (
        ("high", "Bearish RSI Divergence", "bearish"),
        ("low", "Bullish RSI Divergence", "bullish"),
    ):
        same = [p for p in pivots if p.kind == kind]
        # Newest pair first — a stale divergence is not actionable.
        for a, b in zip(reversed(same[:-1]), reversed(same[1:])):
            gap = b.idx - a.idx
            if not (_DIV_MIN_BARS <= gap <= _DIV_MAX_BARS):
                continue
            ra, rb = rsi_at(a.idx), rsi_at(b.idx)
            if ra is None or rb is None or abs(rb - ra) < _DIV_MIN_RSI_GAP:
                continue

            if kind == "high":
                diverges = b.price > a.price and rb < ra
            else:
                diverges = b.price < a.price and rb > ra
            if not diverges:
                continue

            cand = {
                "type": name,
                "direction": direction,
                "from": {"date": _to_dt(a.ts).strftime("%Y-%m-%d"),
                         "price": round(a.price, 4), "rsi": round(ra, 2)},
                "to": {"date": _to_dt(b.ts).strftime("%Y-%m-%d"),
                       "price": round(b.price, 4), "rsi": round(rb, 2)},
                "rsi_gap": round(abs(rb - ra), 2),
                "bars_apart": gap,
            }
            if best is None or cand["to"]["date"] > best["to"]["date"]:
                best = cand
            break  # newest qualifying pair for this side is enough

    if best:
        logger.info(
            "patterns.divergence type=%s gap=%.1f bars=%d",
            best["type"], best["rsi_gap"], best["bars_apart"],
        )
    return best


# ── Plain-language pattern reference ─────────────────────────────────────────

# What each formation is, how it USUALLY resolves, what confirms it and what
# kills it. Written out so the bot can explain itself rather than emitting a
# name and a number: a user who is told "Ascending Triangle, target 5,475" and
# nothing else has no way to judge the call, and no way to know it was
# conditional. Every entry names the invalidation, because the thing that makes
# a pattern honest is stating in advance what would prove it wrong.
#
# "usually" is doing real work in these strings and is deliberate. Classical
# patterns fail often — a breakout that reverses back through the boundary is
# an ordinary outcome, not an anomaly — so none of this is phrased as what the
# price WILL do.
PATTERN_GUIDE: Dict[str, Dict[str, str]] = {
    "Ascending Triangle": {
        "what": "Resistance datar ditekan berulang, sementara support naik — penjual bertahan di satu harga, pembeli berani makin tinggi.",
        "usually": "Lebih sering tembus ke ATAS saat resistance jebol.",
        "confirm": "Close di atas garis resistance, idealnya dengan volume naik.",
        "invalid": "Close di bawah garis support naik — tekanan beli hilang.",
    },
    "Descending Triangle": {
        "what": "Support datar diuji berulang, sementara resistance turun — pembeli bertahan di satu harga, penjual makin agresif.",
        "usually": "Lebih sering tembus ke BAWAH saat support jebol.",
        "confirm": "Close di bawah garis support, idealnya dengan volume naik.",
        "invalid": "Close di atas garis resistance turun.",
    },
    "Symmetrical Triangle": {
        "what": "Harga menyempit dari dua sisi — pembeli dan penjual sama-sama mengecil ruangnya.",
        "usually": "Arahnya BELUM ditentukan; biasanya lanjut ke arah tren sebelum pola terbentuk.",
        "confirm": "Close tegas keluar dari salah satu sisi segitiga.",
        "invalid": "Harga bolak-balik keluar-masuk garis (false break) — pola batal.",
    },
    "Rising Wedge": {
        "what": "Harga masih naik tapi rentangnya menyempit — kenaikan makin kehabisan tenaga.",
        "usually": "Lebih sering pecah ke BAWAH meski trennya sedang naik.",
        "confirm": "Close di bawah garis support wedge.",
        "invalid": "Close tegas di atas garis atas wedge — tren naik berlanjut.",
    },
    "Falling Wedge": {
        "what": "Harga masih turun tapi rentangnya menyempit — tekanan jual mulai habis.",
        "usually": "Lebih sering pecah ke ATAS meski trennya sedang turun.",
        "confirm": "Close di atas garis resistance wedge.",
        "invalid": "Close tegas di bawah garis bawah wedge — penurunan berlanjut.",
    },
    "Bull Flag": {
        "what": "Kenaikan tajam (tiang), lalu istirahat menyamping/menurun tipis dengan volume mengecil.",
        "usually": "Lebih sering LANJUT NAIK sebesar tinggi tiang.",
        "confirm": "Close di atas batas atas flag dengan volume kembali naik.",
        "invalid": "Close di bawah batas bawah flag.",
    },
    "Bear Flag": {
        "what": "Penurunan tajam (tiang), lalu rebound tipis dengan volume mengecil.",
        "usually": "Lebih sering LANJUT TURUN sebesar tinggi tiang.",
        "confirm": "Close di bawah batas bawah flag.",
        "invalid": "Close di atas batas atas flag.",
    },
    "Bull Pennant": {
        "what": "Kenaikan tajam lalu konsolidasi menyempit membentuk segitiga kecil.",
        "usually": "Lebih sering LANJUT NAIK setelah keluar dari pennant.",
        "confirm": "Close di atas garis atas pennant dengan volume naik.",
        "invalid": "Close di bawah garis bawah pennant.",
    },
    "Bear Pennant": {
        "what": "Penurunan tajam lalu konsolidasi menyempit membentuk segitiga kecil.",
        "usually": "Lebih sering LANJUT TURUN setelah keluar dari pennant.",
        "confirm": "Close di bawah garis bawah pennant.",
        "invalid": "Close di atas garis atas pennant.",
    },
    "Double Top": {
        "what": "Dua puncak di harga hampir sama, gagal menembus lebih tinggi.",
        "usually": "Sinyal PEMBALIKAN ke bawah bila neckline jebol.",
        "confirm": "Close di bawah neckline (lembah di antara dua puncak).",
        "invalid": "Close di atas puncak tertinggi — pola batal.",
    },
    "Double Bottom": {
        "what": "Dua lembah di harga hampir sama, gagal turun lebih dalam.",
        "usually": "Sinyal PEMBALIKAN ke atas bila neckline tertembus.",
        "confirm": "Close di atas neckline (puncak di antara dua lembah).",
        "invalid": "Close di bawah lembah terendah — pola batal.",
    },
    "Head and Shoulders": {
        "what": "Tiga puncak: tengah tertinggi, dua bahu lebih rendah dan seimbang.",
        "usually": "Sinyal PEMBALIKAN ke bawah bila neckline jebol.",
        "confirm": "Close di bawah neckline, idealnya dengan volume naik.",
        "invalid": "Close di atas puncak kepala — pola batal.",
    },
    "Inverse Head and Shoulders": {
        "what": "Tiga lembah: tengah terdalam, dua bahu lebih dangkal dan seimbang.",
        "usually": "Sinyal PEMBALIKAN ke atas bila neckline tertembus.",
        "confirm": "Close di atas neckline, idealnya dengan volume naik.",
        "invalid": "Close di bawah lembah kepala — pola batal.",
    },
}


def explain_pattern(name: str) -> Optional[Dict[str, str]]:
    """Reference entry for `name`, or None if the pattern isn't documented."""
    return PATTERN_GUIDE.get(name)
