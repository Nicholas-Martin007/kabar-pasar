"""
Stockpick chart alerts.

Runs the screener, then delivers each qualifying pick to Telegram as a chart
PNG with its plain-language rationale as the caption.

Everything here goes through `backend.tasks.submit` rather than running inline:
one sweep can render a dozen charts, and matplotlib serialises behind a global
lock, so doing it on the caller's stack would stall the SSE stream for the whole
batch. The screener sweep itself is also queued — it fans out ~20 blocking
yfinance calls.

Delivery is opt-in per subscriber via their existing watchlist: a pick is only
pushed to someone already following that ticker, so this cannot turn into an
unsolicited broadcast of every name the screener likes.
"""

import logging
from typing import List, Optional

from backend.db.repository import list_subscribers
from backend.db.session import get_session
from backend.services.chart_service import get_chart_with_rationale
from backend.tasks import submit
from ta_engine.screener import Pick, screen
from telegram_bot.telegram_service import is_enabled, send_message

logger = logging.getLogger(__name__)

# Screener score below which a pick isn't worth a push notification.
_MIN_SCORE = 50


async def send_pick_chart(ticker: str, chat_id: str, score: int, reasons: List[str]) -> None:
    """
    Render `ticker` and deliver chart + rationale to one chat.

    Imported lazily inside the function so a missing/rotated Telegram token
    degrades to a logged warning instead of an import-time failure.
    """
    from telegram_bot.telegram_service import send_photo

    result, rationale = await get_chart_with_rationale(ticker)

    header = (
        f"⭐ <b>Stockpick: {ticker}</b>  (skor {score})\n"
        + "\n".join(f"• {r}" for r in reasons[:4])
        + "\n\n"
    )
    caption = header + rationale

    ok = await send_photo(chat_id, result.chart_path, caption=caption)
    if not ok:
        # Photo upload failed (bad path, Telegram hiccup) — the analysis is
        # still worth delivering, so fall back to text rather than dropping it.
        await send_message(chat_id, caption)
        logger.warning("picks.photo_failed_fellback ticker=%s chat=%s", ticker, chat_id)


async def dispatch_pick_alerts(
    picks: Optional[List[Pick]] = None,
    min_score: int = _MIN_SCORE,
    limit: int = 5,
) -> int:
    """
    Push chart alerts for qualifying picks to subscribers who follow them.

    Returns the number of (pick, chat) jobs queued — not delivered; delivery
    happens on the worker pool.
    """
    if not is_enabled():
        logger.info("picks.telegram_disabled")
        return 0

    if picks is None:
        picks = await screen(limit=limit)
    picks = [p for p in picks if p.score >= min_score][:limit]
    if not picks:
        logger.info("picks.none_qualified min_score=%d", min_score)
        return 0

    async with get_session() as session:
        subs = await list_subscribers(session)
    if not subs:
        return 0

    queued = 0
    for pick in picks:
        base = pick.ticker.replace(".JK", "")
        for sub in subs:
            watching = {t.upper() for t in (sub.get("tickers") or [])}
            # Watchlist-scoped on purpose — see module docstring.
            if base.upper() not in watching:
                continue
            ok = await submit(
                send_pick_chart,
                pick.ticker,
                str(sub["chat_id"]),
                pick.score,
                pick.reasons,
                name=f"pick_chart:{pick.ticker}",
                # One render per ticker+chat per cycle even if the screener
                # surfaces it repeatedly.
                key=f"pick:{pick.ticker}:{sub['chat_id']}",
            )
            queued += int(ok)

    logger.info("picks.dispatched picks=%d queued=%d", len(picks), queued)
    return queued
