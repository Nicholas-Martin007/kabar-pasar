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


# ── Entry planning ───────────────────────────────────────────────────────────

# How far above support the ideal accumulation band extends, in ATR.
ENTRY_BAND_ATR = 0.75
# Beyond this distance from support, price has run and buying here is chasing
# rather than accumulating.
EXTENDED_ATR = 1.5


def build_entry_plan(
    close: float,
    atr: float,
    support: Optional[float],
    stop_loss: Optional[float],
    tp1: Optional[float],
    ticker: Optional[str] = None,
    direction: str = "long",
    breakout_level: Optional[float] = None,
) -> dict:
    """
    Where to actually get in — the piece a target and a stop are useless without.

    Returns a zone (low/high), an optional breakout trigger, a plain-language
    note, and the risk/reward **recomputed at the entry**.

    That last part is the whole reason this isn't a one-liner. TP1/TP2/SL are
    derived from the last close, so quoting any other entry silently changes the
    ratio: filling nearer support shrinks the risk leg and improves R/R, while
    chasing a run-up worsens it. Reporting the headline 1:2 next to a different
    entry price would be quietly wrong, so `rr_at_entry` is computed from the
    zone midpoint and returned alongside.

    A bearish frame or an index gets no buy zone at all — inventing an entry for
    a setup that points down, or for an instrument retail cannot hold, is worse
    than saying nothing.
    """
    out = {
        "entry_low": None,
        "entry_high": None,
        "entry_type": "none",
        "breakout_trigger": None,
        "rr_at_entry": None,
        "note": None,
        "extended": False,
    }

    if direction != "long" or not atr or atr <= 0:
        out["note"] = (
            "Tidak ada zona beli — struktur mengarah turun, tunggu konfirmasi."
            if direction == "short"
            else None
        )
        return out

    idx = is_idx_symbol(ticker)

    def snap(v: float, mode: str) -> float:
        return float(round_to_idx_tick(v, mode)) if idx else round(v, 2)

    # The band sits just above support: that is where risk is smallest and the
    # invalidation is closest, which is the definition of a good entry.
    # The zone must sit STRICTLY BELOW the last price. Capping it at the market
    # (the previous behaviour) meant that whenever price was already near
    # support the band collapsed onto the close and the app effectively printed
    # "ideal buy = current price" — which reads as permission to hajar kanan,
    # chase the offer. An accumulation zone is a level you wait for, not a
    # licence to pay up; if there is no room below, the honest answer is "wait",
    # not a buy price that happens to equal the screen.
    tick = float(idx_tick_size(close)) if idx else max(close * 0.001, 0.01)
    ceiling = close - tick

    if support is not None and support < close:
        low = snap(support, "ceil")
        raw_high = min(support + ENTRY_BAND_ATR * atr, ceiling)
        high = snap(raw_high, "floor")
        distance_atr = (close - support) / atr
        extended = distance_atr > EXTENDED_ATR
        if high < low:
            # Price is sitting on support with no room for a band. Quote the
            # support level itself as the wait-for level rather than the market.
            low = high = snap(support, "nearest")
    else:
        # No support below price — anchor the band on ATR beneath the close so
        # there is still a defined level rather than "buy anywhere". Still
        # strictly below the market, for the same anti-chasing reason.
        low = snap(close - ENTRY_BAND_ATR * atr, "ceil")
        high = snap(ceiling, "floor")
        if high < low:
            low = high
        extended = False

    out["entry_low"], out["entry_high"] = low, high
    out["extended"] = extended

    mid = (low + high) / 2.0
    if stop_loss is not None and tp1 is not None and mid > stop_loss:
        risk = mid - stop_loss
        if risk > 0:
            out["rr_at_entry"] = round((tp1 - mid) / risk, 2)

    if breakout_level is not None and breakout_level > close:
        out["breakout_trigger"] = snap(breakout_level, "ceil")

    # Every branch here describes WAITING for a level. There is deliberately no
    # "buy at market" outcome: the whole point of quoting an entry is to give
    # the user a price to be patient for.
    gap_pct = (close - high) / close * 100 if close else 0.0
    if extended:
        out["entry_type"] = "pullback"
        out["note"] = (
            f"Harga sudah {(close - (support or high)) / atr:.1f}x ATR di atas support — "
            f"beli di harga sekarang berarti mengejar. Tunggu pullback ke zona."
        )
    elif gap_pct <= 1.0:
        out["entry_type"] = "pullback"
        out["note"] = (
            "Harga hanya sedikit di atas zona — sabar menunggu isi di zona "
            "memberi risiko lebih kecil daripada beli di harga sekarang."
        )
    else:
        out["entry_type"] = "pullback"
        out["note"] = (
            f"Tunggu pullback ~{gap_pct:.1f}% ke zona; risiko lebih kecil "
            f"dibanding beli di harga sekarang."
        )

    return out
