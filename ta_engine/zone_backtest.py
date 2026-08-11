"""
Out-of-sample test: do KUAT zones actually hold more often than LEMAH ones?

The strength label is presented to users as structural evidence. That claim is
only worth making if it survives a test, and the test has to be able to FAIL —
so this is deliberately built to be capable of embarrassing the scoring.

## Method

Walk-forward, strictly out of sample:

1. Cut the history at bar `t`. Build zones from data up to `t` ONLY.
2. Look forward from `t` for the first bar that tests a zone (price enters the
   band having approached from clearly outside).
3. Record whether that test HELD (price closed back on the approach side within
   `horizon` bars) or BROKE (closed clear through the far side).
4. Group outcomes by the strength label the zone carried *at the time*.

Point 1 is the whole point. Scoring a zone on the full history and then asking
whether it held during that same history is circular — the hold record is an
input to the score. Every number here comes from bars the scorer never saw.

## What it cannot tell you

Hold rate is not profitability. A level that holds 70% of the time and loses
three times its average gain on the other 30% is a losing trade. This measures
one narrow claim — that the label ranks levels by how often they hold — and
nothing else.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .support_resistance import APPROACH_ATR, Zone, build_zones

logger = logging.getLogger(__name__)

# Bars to allow a test to resolve before calling it undecided.
DEFAULT_HORIZON = 20
# Minimum history before the first cut, so early zones aren't built on nothing.
MIN_WARMUP_BARS = 140
# How often to re-cut the history. Every bar would be ~250 rebuilds per ticker
# for almost identical zone sets; every 5 keeps it honest and affordable.
STEP_BARS = 5


@dataclass
class Outcome:
    ticker: str
    strength: str
    kind: str          # "support" | "resistance"
    held: bool
    resolved: bool     # False when the horizon expired undecided
    score: float
    htf: bool


@dataclass
class BacktestResult:
    outcomes: List[Outcome] = field(default_factory=list)

    def summary(self) -> Dict[str, Dict[str, float]]:
        """Hold rate per strength label, resolved tests only."""
        out: Dict[str, Dict[str, float]] = {}
        for label in ("strong", "medium", "weak"):
            rows = [o for o in self.outcomes if o.strength == label and o.resolved]
            if not rows:
                out[label] = {"n": 0, "hold_rate": float("nan")}
                continue
            held = sum(1 for r in rows if r.held)
            out[label] = {
                "n": len(rows),
                "hold_rate": held / len(rows),
                "held": held,
            }
        return out

    def by_confluence(self) -> Dict[bool, Dict[str, float]]:
        out: Dict[bool, Dict[str, float]] = {}
        for flag in (True, False):
            rows = [o for o in self.outcomes if o.htf is flag and o.resolved]
            if not rows:
                out[flag] = {"n": 0, "hold_rate": float("nan")}
                continue
            held = sum(1 for r in rows if r.held)
            out[flag] = {"n": len(rows), "hold_rate": held / len(rows), "held": held}
        return out


def _first_test_outcome(
    df: pd.DataFrame,
    start: int,
    zone: Zone,
    atr: float,
    horizon: int,
) -> Optional[Tuple[bool, bool]]:
    """
    Find the first forward test of `zone` after `start`.

    Returns (held, resolved), or None if the zone is never tested in the window.
    Mirrors the in-sample test definition exactly, including the approach
    requirement — otherwise the backtest would be scoring a different event from
    the one the label was built on.
    """
    highs = df["High"].to_numpy(dtype=float)
    lows = df["Low"].to_numpy(dtype=float)
    closes = df["Close"].to_numpy(dtype=float)
    n = len(df)
    buf = APPROACH_ATR * atr
    lo, hi = zone.low, zone.high

    i = start + 1
    while i < n:
        if not (lows[i] <= hi and highs[i] >= lo):
            i += 1
            continue

        prior = closes[i - 1]
        if prior > hi + buf:
            from_above = True
        elif prior < lo - buf:
            from_above = False
        else:
            i += 1
            continue  # drifted in from inside: chop, not a test

        # Resolve: leave the band, or run out of horizon.
        j = i
        limit = min(n, i + horizon)
        while j < limit:
            c = closes[j]
            if from_above and c > hi:
                return True, True
            if from_above and c < lo:
                return False, True
            if not from_above and c < lo:
                return True, True
            if not from_above and c > hi:
                return False, True
            j += 1
        return False, False  # undecided within the horizon
    return None


def backtest_ticker(
    df: pd.DataFrame,
    ticker: str,
    horizon: int = DEFAULT_HORIZON,
    step: int = STEP_BARS,
    warmup: int = MIN_WARMUP_BARS,
    use_htf: bool = False,
) -> List[Outcome]:
    """Walk-forward outcomes for one instrument. `df` needs an atr14 column."""
    out: List[Outcome] = []
    n = len(df)
    if n < warmup + horizon + 10:
        return out

    seen: set = set()
    for cut in range(warmup, n - horizon, step):
        past = df.iloc[:cut]
        atr = float(past["atr14"].iloc[-1])
        if not np.isfinite(atr) or atr <= 0:
            continue
        price = float(past["Close"].iloc[-1])

        # Weekly resampling is the expensive part of the walk and changes only
        # the SCORE, not the geometry — off by default so a 30-ticker run stays
        # affordable, on when the confluence bonus itself is under test.
        try:
            zones = build_zones(past, atr, price, use_htf=use_htf)
        except Exception as exc:
            logger.debug("backtest.zones_failed ticker=%s cut=%d err=%s", ticker, cut, exc)
            continue

        for z in zones:
            # One outcome per distinct band per ticker: re-cutting every 5 bars
            # regenerates near-identical zones, and counting each rebuild would
            # inflate n and make a handful of levels look like a large sample.
            key = (round(z.low, 4), round(z.high, 4))
            if key in seen:
                continue
            seen.add(key)

            res = _first_test_outcome(df, cut, z, atr, horizon)
            if res is None:
                continue
            held, resolved = res
            out.append(Outcome(
                ticker=ticker, strength=z.strength, kind=z.kind,
                held=held, resolved=resolved, score=z.score,
                htf=z.htf_confluence,
            ))
    return out


def run(
    frames: Sequence[Tuple[str, pd.DataFrame]],
    horizon: int = DEFAULT_HORIZON,
    use_htf: bool = False,
) -> BacktestResult:
    """Aggregate a walk-forward test across several instruments."""
    result = BacktestResult()
    for ticker, df in frames:
        result.outcomes.extend(
            backtest_ticker(df, ticker, horizon=horizon, use_htf=use_htf)
        )
    return result
