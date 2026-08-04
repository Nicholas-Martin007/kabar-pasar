"""
IDX price-fraction (fraksi harga) helpers.

The Jakarta exchange only accepts orders on fixed price increments that widen
with price. A computed level like 512.23 is not an order anyone can place, so
every price this system shows a user is snapped onto the grid first.

    round_to_idx_tick(512.23)            -> 510
    round_to_idx_tick(512.23, "ceil")    -> 515
    round_to_idx_tick(8922.5)            -> 8925

## Direction matters for trade levels

`nearest` is the default and is right for descriptive prices (support,
resistance). It is the WRONG default for a stop or a target, because nearest
can move the level toward entry — tightening a stop into the noise it was sized
to survive, or shaving a target below the reward the position was taken for.
Those get `floor` and `ceil` respectively, so rounding can only ever be
conservative. See `chart_generator._compute_trade_levels`, which also recomputes
risk from the ROUNDED stop so the 1:2 minimum survives the snap.

## Scope

IDX only. A US symbol has no fraksi harga and cent pricing is already valid, so
`is_idx_symbol()` gates every call — applying a Rp25 grid to a $150 stock would
mangle it.
"""

import math
from typing import Optional, Sequence, Tuple

# Official IDX bands as (exclusive upper bound, tick). Boundaries are inclusive
# at the bottom: exactly 200 pays the Rp2 tick, exactly 5000 the Rp25 tick.
IDX_TICK_BANDS: Sequence[Tuple[float, int]] = (
    (200, 1),
    (500, 2),
    (2000, 5),
    (5000, 10),
    (float("inf"), 25),
)

# Rp50 is the IDX floor price for ordinary equities; nothing may round below it.
IDX_MIN_PRICE = 50


# Friendly names people actually type, mapped to Yahoo symbols. Without this,
# "/chart IHSG" becomes "IHSG.JK" — a symbol that does not exist — and the user
# gets "no price data" for the most important index on the exchange.
_SYMBOL_ALIASES = {
    "IHSG": "^JKSE",
    "JKSE": "^JKSE",
    "COMPOSITE": "^JKSE",
    "IDX": "^JKSE",
    "LQ45": "^JKLQ45",
    "EMAS": "GC=F",
    "GOLD": "GC=F",
    "MINYAK": "CL=F",
    "OIL": "CL=F",
    "USDIDR": "USDIDR=X",
    "RUPIAH": "USDIDR=X",
}


def resolve_symbol(raw: str) -> str:
    """
    Turn user input into a Yahoo symbol.

    Handles the aliases above, leaves anything already qualified (a dot, a "^"
    or an "=") untouched, and otherwise assumes an IDX ticker needing ".JK".
    """
    t = (raw or "").strip().upper()
    if not t:
        return t
    if t in _SYMBOL_ALIASES:
        return _SYMBOL_ALIASES[t]
    if "." in t or t.startswith("^") or "=" in t:
        return t
    return f"{t}.JK"


def is_index_symbol(ticker: Optional[str]) -> bool:
    """Yahoo index symbols lead with "^" and are quoted in points."""
    return bool(ticker) and ticker.strip().startswith("^")


def is_idx_symbol(ticker: Optional[str]) -> bool:
    """True for Jakarta-listed symbols, which are the only ones with fraksi harga."""
    if not ticker:
        return False
    return ticker.strip().upper().endswith(".JK")


def idx_tick_size(price: float) -> int:
    """Minimum price increment at `price`."""
    if not math.isfinite(price) or price < 0:
        return 1
    for upper, tick in IDX_TICK_BANDS:
        if price < upper:
            return tick
    return 25


def round_to_idx_tick(price: float, direction: str = "nearest") -> int:
    """
    Snap `price` onto the IDX price grid.

    Args:
        price: raw computed value.
        direction: "nearest" (default), "floor" (never round up) or "ceil"
            (never round down). Use floor for stops and ceil for targets — see
            the module docstring on why nearest is unsafe there.

    Returns:
        A tradeable integer price, never below IDX_MIN_PRICE.

    A value sitting near a band edge is re-checked after snapping: rounding up
    from 199 lands on 200, which belongs to the next band, and the result must
    be valid in the band it ends up in rather than the one it started in.
    """
    if not math.isfinite(price):
        raise ValueError(f"cannot round non-finite price {price!r}")

    tick = idx_tick_size(price)
    snapped = _snap(price, tick, direction)

    # Crossing a band boundary changes the legal grid; re-snap in the new band.
    # Bounded to one extra pass — the bands are constructed so their boundaries
    # are multiples of the wider tick, so this converges immediately.
    new_tick = idx_tick_size(snapped)
    if new_tick != tick:
        snapped = _snap(float(snapped), new_tick, direction)

    return max(IDX_MIN_PRICE, int(snapped))


def _snap(price: float, tick: int, direction: str) -> int:
    if tick <= 0:
        return int(round(price))
    q = price / tick
    if direction == "floor":
        n = math.floor(q)
    elif direction == "ceil":
        n = math.ceil(q)
    elif direction == "nearest":
        # Round half away from zero. Python's bankers' rounding would send
        # 8922.5/25 = 356.9 fine, but half-way cases like 2005/10 = 200.5 to
        # 200 rather than 201, which is not what a trader expects.
        n = math.floor(q + 0.5)
    else:
        raise ValueError(f"direction must be nearest|floor|ceil, got {direction!r}")
    return int(n * tick)


def round_level(
    price: Optional[float], ticker: Optional[str], direction: str = "nearest"
) -> Optional[float]:
    """
    Round `price` only when `ticker` is IDX-listed; pass through otherwise.

    Returns an int for IDX (no trailing .00 anywhere downstream) and the
    original float for everything else.
    """
    if price is None:
        return None
    if not is_idx_symbol(ticker):
        return price
    return round_to_idx_tick(price, direction)


def format_price(price: Optional[float], currency: str = "IDR") -> str:
    """
    Display string: thousands-separated integer for IDR, 2dp otherwise.

    IDR has no sub-rupiah trading, so decimals on an IDX price are noise that
    also makes the number look more precise than the tick grid allows.
    """
    if price is None:
        return "—"
    if currency == "IDR":
        return f"{int(round(price)):,}"
    return f"{price:,.2f}"
