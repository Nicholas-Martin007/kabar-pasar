"""
Out-of-sample test: does pattern `quality_score` predict anything?

The bot prints "Rising Wedge — kemiripan bentuk 90%" next to price levels, and
filters detections at MIN_QUALITY. Both are claims. The docstrings are careful
to call the number shape conformance rather than a win rate, but nobody had ever
checked whether it correlates with OUTCOME at all — which is a different and
more basic question than whether it is a probability.

Three things this measures:

1. **Directional hit rate** — after a pattern is detected, does price move the
   way the pattern says over the next `horizon` bars?
2. **Lift over base rate** — the same ticker's unconditional probability of
   rising over `horizon` bars. Without this the test is worthless: in a bull
   market every bullish pattern "works", and the number would measure the
   market, not the pattern.
3. **Whether the quality cutoff earns its place** — detections are collected at
   a LOW threshold and bucketed afterwards, so the question "would 0.70 have
   been as good as 0.80?" can actually be answered.

## Honest limits

* A directional hit is not a profitable trade. It ignores path — a setup that
  goes 8% against you before ending up 1% ahead counts as a hit here and would
  have stopped you out in reality.
* Sample sizes per bucket are small. Patterns at MIN_QUALITY are rare by design
  (that is the point of the filter), so a few dozen instances per bucket is
  normal and the confidence intervals are wide. Treat direction of effect as
  the finding, not the decimal places.
* Published evidence on classical chart patterns is mixed at best. A null
  result here would be unsurprising and is a legitimate outcome.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .pattern_detector import detect_patterns

logger = logging.getLogger(__name__)

# Bars to look forward when judging resolution.
DEFAULT_HORIZON = 20
# History required before the first detection cut.
MIN_WARMUP_BARS = 140
# Re-cut every N bars. Patterns persist for a while, so a fine step would
# re-detect the same formation repeatedly; dedupe below handles the rest.
STEP_BARS = 5
# Collect well below the production MIN_QUALITY so the cutoff itself is testable.
SCAN_MIN_QUALITY = 0.55

# Quality buckets for reporting.
_BUCKETS: Tuple[Tuple[float, float, str], ...] = (
    (0.55, 0.70, "0.55-0.70"),
    (0.70, 0.80, "0.70-0.80"),
    (0.80, 0.90, "0.80-0.90"),
    (0.90, 1.01, "0.90-1.00"),
)


@dataclass
class PatternOutcome:
    ticker: str
    pattern: str
    direction: str
    quality: float
    fwd_return: float          # signed return over the horizon
    directional_hit: bool      # moved the way the pattern implies
    hit_target: Optional[bool] # reached target before stop, when levels exist
    base_rate: float           # P(up over horizon) for this ticker
    prior_return: float        # trailing return at detection, for the control
    matched_rate: float        # P(up) among bars with a SIMILAR trailing return


@dataclass
class PatternBacktest:
    outcomes: List[PatternOutcome] = field(default_factory=list)

    def by_bucket(self) -> Dict[str, Dict[str, float]]:
        out: Dict[str, Dict[str, float]] = {}
        for lo, hi, name in _BUCKETS:
            rows = [o for o in self.outcomes if lo <= o.quality < hi]
            out[name] = _stats(rows)
        return out

    def by_direction(self) -> Dict[str, Dict[str, float]]:
        return {
            d: _stats([o for o in self.outcomes if o.direction == d])
            for d in ("bullish", "bearish", "neutral")
        }

    def by_pattern(self, min_n: int = 8) -> Dict[str, Dict[str, float]]:
        names = sorted({o.pattern for o in self.outcomes})
        out = {}
        for n in names:
            rows = [o for o in self.outcomes if o.pattern == n]
            if len(rows) >= min_n:
                out[n] = _stats(rows)
        return out

    def overall(self) -> Dict[str, float]:
        return _stats(self.outcomes)


def _stats(rows: Sequence[PatternOutcome]) -> Dict[str, float]:
    """Hit rate, expected base rate and the lift between them."""
    if not rows:
        return {"n": 0, "hit_rate": float("nan"), "expected": float("nan"),
                "lift_pp": float("nan"), "z": float("nan"), "mean_ret": float("nan"),
                "matched": float("nan"), "lift_matched_pp": float("nan"),
                "z_matched": float("nan"), "target_rate": float("nan")}

    n = len(rows)
    hits = sum(1 for r in rows if r.directional_hit)
    hit_rate = hits / n

    # Expected hit rate under the null: for a bullish call the base rate, for a
    # bearish call its complement. Comparing a bearish pattern against P(up)
    # would score it against the wrong coin.
    expected = float(np.mean([
        r.base_rate if r.direction == "bullish"
        else (1 - r.base_rate) if r.direction == "bearish"
        else 0.5
        for r in rows
    ]))
    matched = float(np.mean([
        r.matched_rate if r.direction == "bullish"
        else (1 - r.matched_rate) if r.direction == "bearish"
        else 0.5
        for r in rows
    ]))
    se = math.sqrt(max(expected * (1 - expected) / n, 1e-12))
    se_m = math.sqrt(max(matched * (1 - matched) / n, 1e-12))
    return {
        "n": n,
        "hit_rate": hit_rate,
        "expected": expected,
        "lift_pp": (hit_rate - expected) * 100,
        "z": (hit_rate - expected) / se,
        "matched": matched,
        "lift_matched_pp": (hit_rate - matched) * 100,
        "z_matched": (hit_rate - matched) / se_m,
        "mean_ret": float(np.mean([r.fwd_return for r in rows])),
        "target_rate": _target_rate(rows),
    }


def _target_rate(rows: Sequence[PatternOutcome]) -> float:
    resolved = [r for r in rows if r.hit_target is not None]
    if not resolved:
        return float("nan")
    return sum(1 for r in resolved if r.hit_target) / len(resolved)


def _target_before_stop(
    df: pd.DataFrame, start: int, levels: Dict[str, float], direction: str, horizon: int
) -> Optional[bool]:
    """
    Did price reach the pattern's measured-move target before its stop?

    Uses intrabar highs/lows, so it is the optimistic reading — when both are
    touched in the same bar it cannot tell which came first and counts the stop,
    which is the conservative half of an otherwise generous measure.
    """
    target = levels.get("target")
    stop = levels.get("stop_loss")
    if target is None or stop is None:
        return None

    highs = df["High"].to_numpy(dtype=float)
    lows = df["Low"].to_numpy(dtype=float)
    end = min(len(df), start + horizon + 1)

    for i in range(start + 1, end):
        if direction == "bearish":
            if lows[i] <= target:
                return True
            if highs[i] >= stop:
                return False
        else:
            if highs[i] >= target:
                return True
            if lows[i] <= stop:
                return False
    return None  # unresolved inside the horizon


def backtest_ticker(
    df: pd.DataFrame,
    ticker: str,
    horizon: int = DEFAULT_HORIZON,
    step: int = STEP_BARS,
    warmup: int = MIN_WARMUP_BARS,
) -> List[PatternOutcome]:
    """Walk-forward pattern outcomes for one instrument."""
    out: List[PatternOutcome] = []
    n = len(df)
    if n < warmup + horizon + 10:
        return out

    closes = df["Close"].to_numpy(dtype=float)

    # Unconditional P(up over `horizon`) for this ticker — the null the pattern
    # has to beat. Computed over the whole sample, so it is the same yardstick
    # for every detection regardless of when it happened.
    fwd = closes[horizon:] / closes[:-horizon] - 1.0
    base_rate = float(np.mean(fwd > 0)) if len(fwd) else 0.5

    # MATCHED control. A bullish pattern found after a slide will look
    # predictive if price simply mean-reverts, and that would be an artifact of
    # WHEN patterns get detected, not evidence the shape means anything. So
    # each detection is also compared against bars with a similar trailing
    # return — same market conditions, no pattern required.
    prior_all = np.full(len(closes), np.nan)
    if len(closes) > horizon:
        prior_all[horizon:] = closes[horizon:] / closes[:-horizon] - 1.0
    up_all = np.full(len(closes), np.nan)
    if len(fwd):
        up_all[: len(fwd)] = (fwd > 0).astype(float)

    valid = ~np.isnan(prior_all) & ~np.isnan(up_all)
    prior_valid = prior_all[valid]
    up_valid = up_all[valid]
    edges = (
        np.quantile(prior_valid, [0.2, 0.4, 0.6, 0.8])
        if len(prior_valid) >= 20 else np.array([0.0])
    )

    def matched_base(prior: float) -> float:
        """P(up) among bars whose trailing return sits in the same quintile."""
        if not len(prior_valid):
            return base_rate
        b = int(np.searchsorted(edges, prior))
        same = up_valid[np.searchsorted(edges, prior_valid) == b]
        return float(np.mean(same)) if len(same) >= 10 else base_rate

    seen: set = set()
    for cut in range(warmup, n - horizon, step):
        past = df.iloc[:cut]
        atr = float(past["atr14"].iloc[-1])
        if not np.isfinite(atr) or atr <= 0:
            continue
        try:
            found = detect_patterns(past, min_quality=SCAN_MIN_QUALITY, atr=atr)
        except Exception as exc:
            logger.debug("pbt.detect_failed %s cut=%d %s", ticker, cut, exc)
            continue

        for p in found:
            # A formation persists across cuts; count it once. Keyed on type and
            # start bar, not on the cut, so re-detections of the same structure
            # don't inflate n the way they would per-scan.
            key = (p.pattern_type, p.start_idx)
            if key in seen:
                continue
            seen.add(key)

            entry = closes[cut - 1]
            future = closes[min(cut - 1 + horizon, n - 1)]
            ret = future / entry - 1.0
            if p.direction == "bullish":
                hit = ret > 0
            elif p.direction == "bearish":
                hit = ret < 0
            else:
                continue  # neutral patterns make no directional claim to score

            prior = float(entry / closes[max(0, cut - 1 - horizon)] - 1.0)
            out.append(PatternOutcome(
                ticker=ticker,
                pattern=p.pattern_type,
                direction=p.direction,
                quality=p.quality_score,
                fwd_return=ret,
                directional_hit=hit,
                hit_target=_target_before_stop(
                    df, cut - 1, p.key_levels or {}, p.direction, horizon
                ),
                base_rate=base_rate,
                prior_return=prior,
                matched_rate=matched_base(prior),
            ))
    return out


def run(
    frames: Sequence[Tuple[str, pd.DataFrame]],
    horizon: int = DEFAULT_HORIZON,
) -> PatternBacktest:
    result = PatternBacktest()
    for ticker, df in frames:
        result.outcomes.extend(backtest_ticker(df, ticker, horizon=horizon))
    return result
