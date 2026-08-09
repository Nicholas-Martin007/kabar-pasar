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
# Built lazily, never at module scope: on Python 3.9 an asyncio primitive binds
# to whichever loop is current when it is constructed, and this module is
# imported long before uvicorn starts the real loop. A guard bound to the wrong
# loop deadlocks every chart request. Created on first use instead, from inside
# the running loop.
_locks_guard: Optional[asyncio.Lock] = None


async def _lock_for(key: str) -> asyncio.Lock:
    global _locks_guard
    if _locks_guard is None:
        _locks_guard = asyncio.Lock()
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


async def attach_news_context(result: ChartResult, ticker: str) -> ChartResult:
    """
    Explain the chart's volume spikes with news about the same ticker.

    Reads from the local news cache rather than re-fetching: the ingestion
    pipeline already holds everything, and a chart request shouldn't fan out to
    twelve RSS feeds.

    Failures are swallowed — the volume/news linkage is an enrichment, and a
    chart without it is still a correct chart.
    """
    from backend.db.repository import query_news
    from backend.db.session import get_session
    from ta_engine.news_context import attach_news, recent_for_ticker, summarise

    base = ticker.strip().upper().split(".")[0].lstrip("^")
    try:
        async with get_session() as session:
            items = await query_news(session, ticker=base, limit=400)
    except Exception as exc:
        logger.warning("chart.news_context_failed ticker=%s error=%s", ticker, exc)
        return result

    news = [n.model_dump() for n in items]

    # Recent headlines are shown UNCONDITIONALLY, not only when they happen to
    # land on a volume spike. Gating on spikes meant most charts carried no news
    # at all, which is the opposite of useful: the reason to read news beside a
    # chart is conviction, and that applies on quiet days too.
    result.recent_news = recent_for_ticker(news, limit=5)

    # Volume spikes stay as their own, separate section — still worth knowing
    # where the unusual activity was, independent of whether news explains it.
    if result.volume_events:
        from ta_engine.news_context import VolumeEvent

        events = [VolumeEvent(**{k: v for k, v in e.items() if k != "explained"})
                  for e in result.volume_events]
        events = attach_news(events, news, ticker)
        result.volume_events = [e.to_dict() for e in events]
        result.volume_summary = summarise(events, result.currency)

    logger.info(
        "chart.news_context ticker=%s recent=%d spikes=%d",
        ticker, len(result.recent_news), len(result.volume_events),
    )
    return result


async def attach_fundamentals(result: ChartResult, ticker: str) -> ChartResult:
    """
    Add the valuation snapshot. Blocking yfinance `.info`, so it runs in a
    thread; failures are swallowed because a chart without fundamentals is
    still a correct chart.

    Skipped for indices — an index has no PER or book value.
    """
    from ta_engine.fundamentals import fetch_fundamentals, summarise
    from ta_engine.price_utils import is_index_symbol

    if is_index_symbol(ticker):
        return result
    try:
        f = await asyncio.to_thread(fetch_fundamentals, ticker)
    except Exception as exc:
        logger.warning("chart.fundamentals_failed ticker=%s error=%s", ticker, exc)
        return result

    result.fundamentals = f.to_dict()
    result.fundamentals_summary = summarise(f)
    if f.suppressed:
        logger.info("chart.fundamentals_suppressed ticker=%s fields=%s",
                    ticker, list(f.suppressed))
    return result


async def get_chart_with_rationale(
    ticker: str, force: bool = False
) -> Tuple[ChartResult, str]:
    """Chart plus its plain-language technical summary (HTML, Telegram-ready)."""
    result = await get_chart(ticker, force=force)
    result = await attach_news_context(result, ticker)
    result = await attach_fundamentals(result, ticker)
    return result, build_rationale(result)
