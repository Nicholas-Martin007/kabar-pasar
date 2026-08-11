"""
IDX trading mechanics for the paper account.

Lot size, transaction costs, auto-rejection bands and session hours — the
friction that decides whether a simulator teaches real habits or bad ones. A
frictionless simulator makes scalping look profitable because the thing that
actually kills retail scalping (round-trip cost) is missing.

## These are configuration, not eternal truths

Lot size and the 0.1% sales tax are stable and statutory. **Broker fees vary by
broker**, and **IDX has changed the auto-rejection bands and session hours
several times** (notably the asymmetric ARB introduced in 2020 and later
reverted). The defaults below are documented starting points, every one is
env-overridable, and none of them should be treated as authoritative — check
the current IDX rulebook and your own broker's fee schedule before relying on
the numbers.

Getting this wrong makes the simulator optimistic, which is the dangerous
direction, so where a value is uncertain the default errs toward MORE friction.
"""

import os
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Optional, Sequence, Tuple

# One lot is 100 shares on IDX. Statutory and stable.
LOT_SIZE = 100

# Round-trip cost. Buy fee is brokerage only; sell adds the 0.1% final income
# tax on gross proceeds (PPh final, statutory) on top of brokerage. Defaults sit
# at the mid of the usual Indonesian retail range — cheaper brokers exist.
BUY_FEE_PCT = float(os.getenv("PAPER_BUY_FEE_PCT", "0.15")) / 100
SELL_FEE_PCT = float(os.getenv("PAPER_SELL_FEE_PCT", "0.25")) / 100

# Starting virtual balance. Rp100 juta is a plausible retail account and buys
# ~156 lots of BBCA or ~448 of TPIA at current prices — enough to build a real
# portfolio, small enough that position sizing still matters.
STARTING_CASH = float(os.getenv("PAPER_STARTING_CASH", "100000000"))

# Auto Reject Atas / Bawah: the daily move limit, by price band. IDX has
# revised these more than once, so they are overridable and deliberately
# treated as approximate. Bands are (exclusive upper price bound, limit %).
_ARA_BANDS: Sequence[Tuple[float, float]] = (
    (200, 0.35),
    (5000, 0.25),
    (float("inf"), 0.20),
)

# JATS session hours, WIB. Friday's sessions differ from Mon-Thu.
_SESSIONS_MON_THU = ((time(9, 0), time(12, 0)), (time(13, 30), time(15, 49)))
_SESSIONS_FRI = ((time(9, 0), time(11, 30)), (time(14, 0), time(15, 49)))

WIB = timezone(timedelta(hours=7))


@dataclass(frozen=True)
class CostBreakdown:
    gross: float
    fee: float
    net: float          # cash out on a buy, cash in on a sell
    fee_pct: float


def shares_for(lots: int) -> int:
    return int(lots) * LOT_SIZE


def buy_cost(price: float, lots: int) -> CostBreakdown:
    """Total cash required, brokerage included."""
    gross = price * shares_for(lots)
    fee = gross * BUY_FEE_PCT
    return CostBreakdown(gross, fee, gross + fee, BUY_FEE_PCT)


def sell_proceeds(price: float, lots: int) -> CostBreakdown:
    """Cash received after brokerage and the 0.1% final sales tax."""
    gross = price * shares_for(lots)
    fee = gross * SELL_FEE_PCT
    return CostBreakdown(gross, fee, gross - fee, SELL_FEE_PCT)


def breakeven_price(avg_buy_price: float) -> float:
    """
    Price at which a position clears both legs of cost.

    Worth surfacing to the user: at the default fees a position must move about
    0.4% before it stops losing money, which is why very short scalps rarely
    work in practice.
    """
    return avg_buy_price * (1 + BUY_FEE_PCT) / (1 - SELL_FEE_PCT)


def ara_arb_limits(prev_close: float) -> Tuple[float, float]:
    """(lower_limit, upper_limit) for the session, from the previous close."""
    pct = 0.20
    for upper, band in _ARA_BANDS:
        if prev_close < upper:
            pct = band
            break
    return prev_close * (1 - pct), prev_close * (1 + pct)


def within_auto_reject(price: float, prev_close: float) -> bool:
    lo, hi = ara_arb_limits(prev_close)
    return lo <= price <= hi


def market_phase(now: Optional[datetime] = None) -> str:
    """
    "open" | "closed" | "weekend", in WIB.

    Orders placed while closed are QUEUED rather than rejected — that mirrors
    reality, where you can enter an order pre-market for the next session.
    """
    now = (now or datetime.now(timezone.utc)).astimezone(WIB)
    if now.weekday() >= 5:
        return "weekend"
    sessions = _SESSIONS_FRI if now.weekday() == 4 else _SESSIONS_MON_THU
    t = now.time()
    for start, end in sessions:
        if start <= t <= end:
            return "open"
    return "closed"


def describe_costs() -> str:
    """One-line cost summary for the bot, so fees are never a surprise."""
    return (
        f"Biaya simulasi: beli {BUY_FEE_PCT * 100:.2f}%, "
        f"jual {SELL_FEE_PCT * 100:.2f}% (sudah termasuk pajak final 0,1%). "
        f"1 lot = {LOT_SIZE} lembar."
    )


@dataclass(frozen=True)
class PositionSize:
    lots: int
    shares: int
    entry: float
    stop: float
    risk_per_share: float
    risk_total: float          # rupiah at risk if the stop fills exactly
    risk_pct_of_equity: float
    cost: float                # cash needed to open, fees included
    cost_pct_of_equity: float
    capped_by_cash: bool       # sizing was limited by the balance, not by risk


def size_position(
    equity: float,
    cash: float,
    entry: float,
    stop: float,
    risk_pct: float = 1.0,
) -> Optional[PositionSize]:
    """
    How many lots to buy so that being stopped out costs `risk_pct` of equity.

    This is the arithmetic that turns "I like this stock" into a position, and
    it is the part retail most often skips — position size, not entry price, is
    what decides whether a losing trade is survivable. Chasing the offer with an
    arbitrary lot count is exactly the habit the rest of this bot tries not to
    encourage.

    Risk is measured to the STOP, and the stop distance includes both legs of
    transaction cost, so the number is what actually leaves the account rather
    than the naive (entry - stop) x shares.

    Returns None when the inputs cannot produce a position: a stop at or above
    entry, or a risk budget too small to afford a single lot.
    """
    if entry <= 0 or stop <= 0 or stop >= entry or risk_pct <= 0 or equity <= 0:
        return None

    # Cost-aware risk per share: what is lost buying at `entry` and selling at
    # `stop`, both legs of fees included.
    per_share = (entry * (1 + BUY_FEE_PCT)) - (stop * (1 - SELL_FEE_PCT))
    if per_share <= 0:
        return None

    budget = equity * (risk_pct / 100.0)
    lots = int(budget // (per_share * LOT_SIZE))
    capped = False

    # Never size beyond the cash actually available.
    affordable = int(cash // (entry * (1 + BUY_FEE_PCT) * LOT_SIZE))
    if affordable < lots:
        lots, capped = affordable, True
    if lots < 1:
        return None

    shares = lots * LOT_SIZE
    risk_total = per_share * shares
    cost = buy_cost(entry, lots).net
    return PositionSize(
        lots=lots,
        shares=shares,
        entry=entry,
        stop=stop,
        risk_per_share=per_share,
        risk_total=risk_total,
        risk_pct_of_equity=risk_total / equity * 100.0,
        cost=cost,
        cost_pct_of_equity=cost / equity * 100.0,
        capped_by_cash=capped,
    )
