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

from backend.db.repository import upsert_news_items
from backend.db.session import get_session
from backend.services.events import bus
from ai_engine.ai_summarizer import summarize_batch
from scrapers.rss_service import fetch_all_news
from telegram_bot.telegram_service import (
    dispatch_alerts,
    dispatch_digest,
    dispatch_index_reminders,
    dispatch_paper_fills,
    send_test_news,
)

logger = logging.getLogger(__name__)

_AI_BATCH = int(os.getenv("AI_SUMMARY_BATCH", "10"))
_REFRESH_MIN = int(os.getenv("REFRESH_INTERVAL_MIN", "5"))
_DIGEST_HOUR_WIB = int(os.getenv("DIGEST_HOUR_WIB", "17"))  # 17:00 WIB default
# Hourly "to read" digest: top N news every N hours (0 = off).
_HOURLY_DIGEST_HOURS = int(os.getenv("HOURLY_DIGEST_HOURS", "1"))
_HOURLY_DIGEST_COUNT = int(os.getenv("HOURLY_DIGEST_COUNT", "10"))
# Hour (WIB) for the daily MSCI/FTSE index-review check. Morning, so a T-3
# heads-up lands before the session rather than after it.
_INDEX_REMINDER_HOUR_WIB = int(os.getenv("INDEX_REMINDER_HOUR_WIB", "8"))
# How often to match resting paper-trading orders against live prices, in
# minutes (0 = off). Quotes are only pulled for tickers that actually have an
# open order, and the job no-ops outside JATS hours, so this is cheap.
_PAPER_MATCH_MIN = int(os.getenv("PAPER_MATCH_INTERVAL_MIN", "2"))
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

    # Push to live clients immediately, before the slower AI/Telegram steps —
    # the fast poller covers only 3 feeds, so this is how the other 9 sources
    # reach a connected app without a reload.
    if new_items:
        bus.publish_news([n.model_dump(by_alias=True, mode="json") for n in new_items])

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


async def index_reminder_job() -> None:
    """
    Daily MSCI/FTSE review check.

    Runs every day but only SENDS at T-3 and on the announcement date — see
    due_reminders(). Scheduling the check daily is what makes the reminder
    reliable; the calendar and formatter already existed but nothing invoked
    them, so no reminder had ever fired.
    """
    try:
        sent = await dispatch_index_reminders()
        if sent:
            logger.info("scheduler.index_reminder.sent count=%d", sent)
    except Exception as exc:
        logger.warning("scheduler.index_reminder_failed error=%s", exc)


async def paper_match_job() -> None:
    """Fill resting paper orders (limit / SL / TP / trailing) and notify."""
    try:
        await dispatch_paper_fills()
    except Exception as exc:
        logger.warning("scheduler.paper_match_failed error=%s", exc)


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

    # Daily index-review check (MSCI + FTSE). Silent unless a review is at
    # T-3 or today.
    _scheduler.add_job(
        index_reminder_job,
        trigger=CronTrigger(
            hour=(_INDEX_REMINDER_HOUR_WIB - 7) % 24, minute=5, timezone=timezone.utc
        ),
        id="index_reminders",
        name="MSCI/FTSE index review reminder",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )

    # Paper-trading order matcher. Self-skips when the market is closed.
    if _PAPER_MATCH_MIN > 0:
        _scheduler.add_job(
            paper_match_job,
            trigger=IntervalTrigger(minutes=_PAPER_MATCH_MIN),
            id="paper_match",
            name="Match paper trading orders",
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
