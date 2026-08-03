"""
Async wrapper around the (blocking) TA chart generator.

`ta_engine.generate_chart` does a synchronous yfinance download and a matplotlib
render — together a few seconds of blocking work. Calling it directly from a
FastAPI handler would stall the whole event loop, freezing the SSE/WebSocket
stream and every other request for the duration. So:

* the work runs in a worker thread (`asyncio.to_thread`),
* results are cached per ticker for `_TTL_SEC` (daily bars don't change often
  enough to justify re-rendering per request),
* concurrent requests for the SAME ticker share one render via a per-ticker lock
  (single-flight) instead of each spawning a duplicate.

Without the single-flight guard, ten users tapping the same stock would queue ten
matplotlib renders behind the module's global render lock.
"""

import asyncio
import logging
import time
from typing import Dict, Optional, Tuple

from ta_engine import ChartResult, generate_chart
from ta_engine.narrative import build_rationale

logger = logging.getLogger(__name__)

# Daily candles only change once a day, but intraday the last candle moves.
# 5 minutes keeps it fresh without re-rendering on every tap.
_TTL_SEC = 300

_cache: Dict[str, Tuple[float, ChartResult]] = {}
_locks: Dict[str, asyncio.Lock] = {}
_locks_guard = asyncio.Lock()


async def _lock_for(key: str) -> asyncio.Lock:
    async with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _locks[key] = lock
        return lock


def _cached(key: str) -> Optional[ChartResult]:
    hit = _cache.get(key)
    if hit and (time.time() - hit[0]) < _TTL_SEC:
        return hit[1]
    return None


async def get_chart(ticker: str, force: bool = False) -> ChartResult:
    """
    Generate (or reuse) the daily TA chart for `ticker`.

    Raises ValueError for unknown symbols / insufficient history — the caller
    maps that to a 404/422.
    """
    key = ticker.strip().upper()

    if not force:
        hit = _cached(key)
        if hit is not None:
            return hit

    lock = await _lock_for(key)
    async with lock:
        # Re-check inside the lock: whoever we queued behind may have just
        # produced exactly what we need.
        if not force:
            hit = _cached(key)
            if hit is not None:
                return hit

        started = time.perf_counter()
        result = await asyncio.to_thread(generate_chart, key)
        elapsed = time.perf_counter() - started

        _cache[key] = (time.time(), result)
        logger.info("chart.generated ticker=%s elapsed=%.2fs", key, elapsed)
        return result


async def get_chart_with_rationale(
    ticker: str, force: bool = False
) -> Tuple[ChartResult, str]:
    """Chart plus its plain-language technical summary (HTML, Telegram-ready)."""
    result = await get_chart(ticker, force=force)
    return result, build_rationale(result)
