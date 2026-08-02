"""
Commodity price tracker (yfinance).

Polls a fixed basket every `COMMODITY_POLL_SECONDS` (default 30), stores each
observed price change in `commodity_price`, and broadcasts updates to connected
clients via the event bus.

## Real futures vs. equity proxies — read before adding symbols

Yahoo exposes free continuous futures for gold, oil and copper, but **not for
coal or nickel**. Every documented free symbol for those (`MTF=F`, `LFF=F`,
`ATW=F`, `NID=F`, `NI=F`, `JJN`) returns no data — verified, not assumed.

So coal and nickel are tracked through *equity proxies*: shares in Indonesian
miners whose revenue tracks the underlying commodity. These are flagged
`is_proxy=True` and named accordingly ("Coal miners (proxy)"), because a
miner's share price is not a commodity price — it also carries company
earnings, IDX sentiment, FX and dividend effects. Presenting ADRO.JK to a
retail investor as "the coal price" would be misleading, so the flag must
survive all the way to the UI.

Proxies are also IDR-denominated and only trade during IDX hours, while the
futures are USD and nearly 24h. Do not compare them on one axis.

Env:
  COMMODITY_POLL_SECONDS   interval (default 30, floor 10)
  COMMODITY_POLL_ENABLED   "0" to disable (default "1")
"""

import asyncio
import logging
import os
import random
from dataclasses import dataclass
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_INTERVAL = max(10, int(os.getenv("COMMODITY_POLL_SECONDS", "30")))
_ENABLED = os.getenv("COMMODITY_POLL_ENABLED", "1") != "0"

_MAX_BACKOFF = 600.0
_BACKOFF_FACTOR = 2.0

# Relative move below which we treat the price as unchanged and skip the write.
# Guards against float noise churning the history table.
_EPSILON = 1e-9


@dataclass(frozen=True)
class Commodity:
    symbol: str
    name: str
    currency: str
    is_proxy: bool = False


# Verified working on Yahoo as of 2026-08-02.
BASKET: List[Commodity] = [
    # ── Real futures ────────────────────────────────────────────────────────
    Commodity("GC=F", "Gold", "USD"),
    Commodity("CL=F", "WTI Crude Oil", "USD"),
    Commodity("BZ=F", "Brent Crude Oil", "USD"),
    # ── Equity proxies — NOT commodity prices (see module docstring) ────────
    Commodity("ADRO.JK", "Coal miners (proxy: Adaro)", "IDR", is_proxy=True),
    Commodity("PTBA.JK", "Coal miners (proxy: Bukit Asam)", "IDR", is_proxy=True),
    Commodity("ITMG.JK", "Coal miners (proxy: Indo Tambangraya)", "IDR", is_proxy=True),
    Commodity("INCO.JK", "Nickel miners (proxy: Vale Indonesia)", "IDR", is_proxy=True),
    Commodity("ANTM.JK", "Nickel miners (proxy: Aneka Tambang)", "IDR", is_proxy=True),
]

_BY_SYMBOL: Dict[str, Commodity] = {c.symbol: c for c in BASKET}

# Last price seen per symbol, so we only persist actual moves.
_last_price: Dict[str, float] = {}


def _fetch_batch_blocking(symbols: List[str]) -> Dict[str, dict]:
    """
    Blocking yfinance call — run via asyncio.to_thread.

    Uses one batched `Tickers` request rather than N individual ones: fewer
    round-trips to Yahoo and far less likely to trip their rate limiter.
    """
    import yfinance as yf

    out: Dict[str, dict] = {}
    tickers = yf.Tickers(" ".join(symbols))
    for sym in symbols:
        try:
            info = tickers.tickers[sym].fast_info
            price = info.get("lastPrice") if hasattr(info, "get") else info.last_price
            prev = info.get("previousClose") if hasattr(info, "get") else info.previous_close
            if price is None:
                continue
            price = float(price)
            prev_f = float(prev) if prev else None
            change = round(price - prev_f, 4) if prev_f else None
            change_pct = (
                round((price - prev_f) / prev_f * 100, 4) if prev_f else None
            )
            out[sym] = {"price": price, "change": change, "change_percent": change_pct}
        except Exception as exc:  # one bad symbol must not sink the batch
            logger.debug("commodity.symbol_failed symbol=%s error=%s", sym, exc)
    return out


async def fetch_prices(symbols: Optional[List[str]] = None) -> List[dict]:
    """Fetch current prices. Returns JSON-safe dicts (empty on total failure)."""
    syms = symbols or [c.symbol for c in BASKET]
    try:
        raw = await asyncio.to_thread(_fetch_batch_blocking, syms)
    except Exception as exc:
        logger.warning("commodity.fetch_failed error=%s", exc)
        return []

    quotes: List[dict] = []
    for sym, vals in raw.items():
        meta = _BY_SYMBOL.get(sym)
        if meta is None:
            continue
        quotes.append({
            "symbol": sym,
            "name": meta.name,
            "currency": meta.currency,
            "isProxy": meta.is_proxy,
            "price": vals["price"],
            "change": vals["change"],
            "changePercent": vals["change_percent"],
        })
    return quotes


def _changed(sym: str, price: float) -> bool:
    prev = _last_price.get(sym)
    if prev is None:
        return True
    return abs(price - prev) > max(_EPSILON, abs(prev) * 1e-9)


async def persist_and_broadcast(quotes: List[dict]) -> int:
    """Store only moved prices; broadcast every quote so clients stay in sync."""
    if not quotes:
        return 0

    from backend.db.repository import insert_commodity_prices
    from backend.db.session import get_session
    from backend.services.events import bus

    moved = [q for q in quotes if _changed(q["symbol"], q["price"])]
    if moved:
        async with get_session() as session:
            await insert_commodity_prices(session, moved)
        for q in moved:
            _last_price[q["symbol"]] = q["price"]

    # Broadcast all quotes (not just moved) — a client that just connected
    # needs the current level even if it hasn't ticked.
    bus.publish_commodity(quotes)
    return len(moved)


async def poll_loop() -> None:
    """Run forever. Cancelled on app shutdown."""
    if not _ENABLED:
        logger.info("commodity.disabled COMMODITY_POLL_ENABLED=0")
        return

    logger.info(
        "commodity.started symbols=%d interval=%ds futures=%d proxies=%d",
        len(BASKET), _INTERVAL,
        sum(1 for c in BASKET if not c.is_proxy),
        sum(1 for c in BASKET if c.is_proxy),
    )

    failures = 0
    while True:
        try:
            quotes = await fetch_prices()
            if quotes:
                stored = await persist_and_broadcast(quotes)
                failures = 0
                logger.debug(
                    "commodity.cycle quotes=%d stored=%d", len(quotes), stored
                )
            else:
                failures += 1
        except asyncio.CancelledError:
            logger.info("commodity.stopped")
            raise
        except Exception as exc:
            failures += 1
            logger.warning("commodity.cycle_failed error=%s", exc)

        if failures:
            delay = min(_INTERVAL * (_BACKOFF_FACTOR ** failures), _MAX_BACKOFF)
            delay *= 1.0 + random.uniform(-0.25, 0.25)
            logger.warning(
                "commodity.backoff failures=%d sleeping=%.0fs", failures, delay
            )
        else:
            delay = _INTERVAL * (1.0 + random.uniform(-0.1, 0.1))

        await asyncio.sleep(delay)
