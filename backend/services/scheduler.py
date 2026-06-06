"""
Background news refresh: APScheduler job that fetches every source and
summarises new items. Runs on a configurable interval (REFRESH_INTERVAL_MIN).
"""

import logging
import os
from typing import Dict, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from db.repository import upsert_news_items
from db.session import get_session
from services.ai_summarizer import summarize_batch
from services.rss_service import fetch_all_news
from services.telegram_service import dispatch_alerts

logger = logging.getLogger(__name__)

_AI_BATCH = int(os.getenv("AI_SUMMARY_BATCH", "10"))
_REFRESH_MIN = int(os.getenv("REFRESH_INTERVAL_MIN", "5"))

_scheduler: Optional[AsyncIOScheduler] = None


async def refresh_news_job() -> Dict[str, int]:
    """
    1. Fetch from every source in parallel.
    2. Persist NEW items (existing ids skipped).
    3. Summarise the top _AI_BATCH new items via Claude (cached items skipped).
    Returns counts for logging / /refresh endpoint response.
    """
    logger.info("scheduler.refresh.start")
    items = await fetch_all_news()
    fetched = len(items)

    async with get_session() as session:
        new_items = await upsert_news_items(session, items)
        # Cost control: only summarise the freshest _AI_BATCH items per cycle
        to_summarise = new_items[:_AI_BATCH]
        stats = await summarize_batch(session, to_summarise)

    # Push Telegram alerts for new watchlist-matching items (no-op if disabled).
    alerts_sent = await dispatch_alerts(new_items)

    result = {
        "fetched":    fetched,
        "new":        len(new_items),
        "summarised": stats["summarised"],
        "skipped":    stats["skipped"],
        "errors":     stats["errors"],
        "alerts":     alerts_sent,
    }
    logger.info(
        "scheduler.refresh.done fetched=%d new=%d summarised=%d errors=%d",
        result["fetched"], result["new"], result["summarised"], result["errors"],
    )
    return result


def start_scheduler() -> AsyncIOScheduler:
    """Idempotent — safe to call once on FastAPI startup."""
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        refresh_news_job,
        trigger=IntervalTrigger(minutes=_REFRESH_MIN),
        id="refresh_news",
        name="Refresh news from all sources",
        max_instances=1,    # never overlap if a cycle runs long
        coalesce=True,      # collapse missed runs into one
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("scheduler.started interval_min=%d ai_batch=%d", _REFRESH_MIN, _AI_BATCH)
    return _scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("scheduler.stopped")
