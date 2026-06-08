"""
Background news refresh: APScheduler job that fetches every source and
summarises new items. Runs on a configurable interval (REFRESH_INTERVAL_MIN).
"""

import logging
import os
from datetime import timezone
from typing import Dict, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from db.repository import upsert_news_items
from db.session import get_session
from services.ai_summarizer import summarize_batch
from services.rss_service import fetch_all_news
from services.telegram_service import dispatch_alerts, dispatch_digest, send_test_news

logger = logging.getLogger(__name__)

_AI_BATCH = int(os.getenv("AI_SUMMARY_BATCH", "10"))
_REFRESH_MIN = int(os.getenv("REFRESH_INTERVAL_MIN", "5"))
_DIGEST_HOUR_WIB = int(os.getenv("DIGEST_HOUR_WIB", "17"))  # 17:00 WIB default
# Hourly "to read" digest: top N news every N hours (0 = off).
_HOURLY_DIGEST_HOURS = int(os.getenv("HOURLY_DIGEST_HOURS", "1"))
_HOURLY_DIGEST_COUNT = int(os.getenv("HOURLY_DIGEST_COUNT", "10"))
# Testing only: send a Telegram ping every N seconds (0 = off). Never use in prod.
_TEST_ALERT_SECONDS = int(os.getenv("TEST_ALERT_SECONDS", "0"))

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

    # Cost control: only summarise the freshest _AI_BATCH items per cycle.
    # summarize_batch manages its own per-task sessions.
    stats = await summarize_batch(new_items[:_AI_BATCH])

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


async def daily_digest_job() -> None:
    try:
        sent = await dispatch_digest()
        logger.info("scheduler.digest.done sent=%d", sent)
    except Exception as exc:
        logger.warning("scheduler.digest_failed error=%s", exc)


async def hourly_digest_job() -> None:
    try:
        sent = await dispatch_digest(limit=_HOURLY_DIGEST_COUNT)
        logger.info("scheduler.hourly_digest.done sent=%d", sent)
    except Exception as exc:
        logger.warning("scheduler.hourly_digest_failed error=%s", exc)


async def test_ping_job() -> None:
    try:
        await send_test_news()
    except Exception as exc:
        logger.warning("scheduler.test_ping_failed error=%s", exc)


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
    # Daily Telegram digest at DIGEST_HOUR_WIB (scheduled in UTC).
    _scheduler.add_job(
        daily_digest_job,
        trigger=CronTrigger(
            hour=(_DIGEST_HOUR_WIB - 7) % 24, minute=0, timezone=timezone.utc
        ),
        id="daily_digest",
        name="Daily Telegram digest",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    # Hourly "to read" digest (top N news per N hours).
    if _HOURLY_DIGEST_HOURS > 0:
        _scheduler.add_job(
            hourly_digest_job,
            trigger=IntervalTrigger(hours=_HOURLY_DIGEST_HOURS),
            id="hourly_digest",
            name="Hourly news digest",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )

    # Testing only: rapid Telegram ping to evaluate delivery.
    if _TEST_ALERT_SECONDS > 0:
        _scheduler.add_job(
            test_ping_job,
            trigger=IntervalTrigger(seconds=_TEST_ALERT_SECONDS),
            id="test_ping",
            name="Test Telegram ping",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
        logger.warning(
            "scheduler.TEST_ALERT enabled every %ds — for testing only, "
            "set TEST_ALERT_SECONDS=0 to disable",
            _TEST_ALERT_SECONDS,
        )

    _scheduler.start()
    logger.info(
        "scheduler.started interval_min=%d ai_batch=%d digest_hour_wib=%d",
        _REFRESH_MIN, _AI_BATCH, _DIGEST_HOUR_WIB,
    )
    return _scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("scheduler.stopped")
