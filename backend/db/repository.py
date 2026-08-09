"""
Data-access helpers — keep SQL out of services & routers.

`upsert_news_items` returns IDs of *newly* inserted rows so the scheduler
knows which items need AI summarisation.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import Text, select
# SQLite dialect insert for ON CONFLICT DO NOTHING. If DATABASE_URL is ever
# pointed at PostgreSQL (the documented swap), import its insert instead —
# the on_conflict_do_nothing API is the same shape.
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models.news import News, NewsCategory, NewsImportance, NewsSource

from scrapers.msci_tracker import classify_msci

from .models import AISummaryRow, CommodityPriceRow, NewsRow, TelegramSubscriber

logger = logging.getLogger(__name__)


# ── Conversions ───────────────────────────────────────────────────────────────

def _row_to_news(row: NewsRow) -> News:
    summary = row.ai_summary
    return News(
        id=row.id,
        title=row.title,
        source=NewsSource(row.source),
        published_at=row.published_at,
        excerpt=row.excerpt or "",
        ai_summary=(summary.summary if summary else []) or [],
        impact=summary.impact if summary else None,
        tickers=row.tickers or [],
        importance=NewsImportance(
            summary.importance if summary and summary.importance else row.importance
        ),
        category=NewsCategory(row.category),
        url=row.url,
        # Rows predating the MSCI columns read back as NULL, not False.
        is_msci_alert=bool(row.is_msci_alert),
        priority=row.priority or "NORMAL",
    )


# ── Writes ────────────────────────────────────────────────────────────────────

async def upsert_news_items(session: AsyncSession, items: List[News]) -> List[News]:
    """
    Insert news rows that don't exist yet. Returns the NEW items only.

    Uses INSERT .. ON CONFLICT DO NOTHING .. RETURNING id, which is ATOMIC.

    The previous SELECT-then-INSERT was a time-of-check/time-of-use race, and it
    fired in production: the fast poller and the scheduled refresh both start at
    boot, both fetched the same Yahoo article, both saw "not present", and the
    second INSERT died on the unique constraint — taking the whole fast-poll
    cycle down with it. Checking first cannot fix that, because any gap between
    the check and the write is a window for the other producer. The database has
    to arbitrate.

    RETURNING is what keeps `new_items` truthful under the same race: only the
    producer whose row actually landed sees it as new, so alerts and AI
    summarisation still fire exactly once.
    """
    if not items:
        return []

    # Classify at write time so the flag is durable: the alert path, the API and
    # any later re-read all see the same decision.
    rows = []
    by_id: Dict[str, News] = {}
    now = datetime.now(timezone.utc)
    for item in items:
        if item.id in by_id:
            continue  # same article twice within one batch
        msci = classify_msci(item.title, item.excerpt or "")
        item.is_msci_alert = msci["is_msci_alert"]
        item.priority = msci["priority"]
        by_id[item.id] = item
        rows.append({
            "id": item.id,
            "title": item.title,
            "source": item.source.value,
            "published_at": item.published_at,
            "excerpt": item.excerpt,
            "tickers": item.tickers,
            "importance": item.importance.value,
            "category": item.category.value,
            "url": item.url,
            "is_msci_alert": item.is_msci_alert,
            "priority": item.priority,
            "created_at": now,
            "updated_at": now,
        })

    stmt = (
        sqlite_insert(NewsRow)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["id"])
        .returning(NewsRow.id)
    )
    inserted_ids = set((await session.execute(stmt)).scalars().all())
    await session.commit()

    new_items = [by_id[i] for i in inserted_ids if i in by_id]
    logger.info(
        "repo.upsert total=%d existing=%d new=%d",
        len(rows), len(rows) - len(new_items), len(new_items),
    )
    return new_items


async def save_summary(
    session: AsyncSession,
    news_id: str,
    summary: List[str],
    importance: str,
    impact: Optional[str],
) -> None:
    """Insert or replace AI summary for a news item."""
    existing = await session.get(AISummaryRow, news_id)
    if existing:
        existing.summary = summary
        existing.importance = importance
        existing.impact = impact
    else:
        session.add(AISummaryRow(
            news_id=news_id,
            summary=summary,
            importance=importance,
            impact=impact,
        ))
    await session.commit()


# ── Reads ─────────────────────────────────────────────────────────────────────

async def get_cached_summary(
    session: AsyncSession, news_id: str
) -> Optional[Dict[str, Any]]:
    row = await session.get(AISummaryRow, news_id)
    if row is None:
        return None
    return {"summary": row.summary or [], "importance": row.importance, "impact": row.impact}


async def query_news(
    session: AsyncSession,
    source: Optional[str] = None,
    importance: Optional[str] = None,
    ticker: Optional[str] = None,
    limit: int = 50,
) -> List[News]:
    """Read news with eager-loaded ai_summary, applying optional filters."""
    stmt = (
        select(NewsRow)
        .options(selectinload(NewsRow.ai_summary))
        .order_by(NewsRow.published_at.desc())
    )
    if source:
        stmt = stmt.where(NewsRow.source == source)
    if importance:
        stmt = stmt.where(NewsRow.importance == importance)

    if ticker:
        # Filter in SQL, BEFORE the limit. This used to run in Python on the
        # already-limited rows, which silently returned nothing whenever the
        # ticker's articles fell outside the newest `limit`: BBCA had 18 stories
        # cached and the query answered zero, because none were in the most
        # recent 400. That hit /news?ticker= and the per-chart news feed alike.
        #
        # `tickers` is a JSON array of bare codes, so a LIKE on the quoted code
        # is an exact element match — '"BBCA"' cannot collide with a longer
        # code. Not index-backed, but the table is small and correctness here
        # matters more than the scan.
        stmt = stmt.where(NewsRow.tickers.cast(Text).like(f'%"{ticker.upper()}"%'))

    stmt = stmt.limit(limit)
    rows = (await session.execute(stmt)).scalars().all()
    return [_row_to_news(r) for r in rows]


async def count_news(session: AsyncSession) -> int:
    from sqlalchemy import func
    return (await session.execute(select(func.count(NewsRow.id)))).scalar_one()


# ── Telegram subscribers ──────────────────────────────────────────────────────

async def ensure_subscriber(session: AsyncSession, chat_id: str) -> None:
    # New /start subscribers default to ALL news (opt-out via /mute or /all off).
    if await session.get(TelegramSubscriber, chat_id) is None:
        session.add(
            TelegramSubscriber(
                chat_id=chat_id, tickers=[], keywords=[], mute=[], all_news=True
            )
        )
        await session.commit()


async def get_subscriber_tickers(session: AsyncSession, chat_id: str) -> List[str]:
    sub = await session.get(TelegramSubscriber, chat_id)
    return list(sub.tickers or []) if sub else []


async def add_subscriber_ticker(
    session: AsyncSession, chat_id: str, ticker: str
) -> List[str]:
    sub = await session.get(TelegramSubscriber, chat_id)
    if sub is None:
        sub = TelegramSubscriber(chat_id=chat_id, tickers=[])
        session.add(sub)
    tickers = list(sub.tickers or [])
    if ticker not in tickers:
        tickers.append(ticker)
    sub.tickers = sorted(tickers)  # reassign so SQLAlchemy tracks the JSON change
    await session.commit()
    return sub.tickers


async def remove_subscriber_ticker(
    session: AsyncSession, chat_id: str, ticker: str
) -> List[str]:
    sub = await session.get(TelegramSubscriber, chat_id)
    if sub is None:
        return []
    sub.tickers = [t for t in (sub.tickers or []) if t != ticker]
    await session.commit()
    return sub.tickers


async def remove_subscriber(session: AsyncSession, chat_id: str) -> None:
    sub = await session.get(TelegramSubscriber, chat_id)
    if sub is not None:
        await session.delete(sub)
        await session.commit()


async def list_subscribers(session: AsyncSession) -> List[Dict[str, Any]]:
    rows = (await session.execute(select(TelegramSubscriber))).scalars().all()
    # Must include the control-panel fields — the dispatcher filters on them.
    return [_subscriber_dict(r) for r in rows]


async def get_subscriber(
    session: AsyncSession, chat_id: str
) -> Optional[Dict[str, Any]]:
    r = await session.get(TelegramSubscriber, chat_id)
    if r is None:
        return None
    return {
        "chat_id": r.chat_id,
        "tickers": list(r.tickers or []),
        "keywords": list(r.keywords or []),
        "mute": list(r.mute or []),
        "all_news": bool(r.all_news),
        "high_only": bool(r.high_only),
    }


async def add_subscriber_mute(
    session: AsyncSession, chat_id: str, keyword: str
) -> List[str]:
    kw = keyword.strip().lower()
    sub = await session.get(TelegramSubscriber, chat_id)
    if sub is None:
        sub = TelegramSubscriber(
            chat_id=chat_id, tickers=[], keywords=[], mute=[], all_news=True
        )
        session.add(sub)
    words = list(sub.mute or [])
    if kw and kw not in words:
        words.append(kw)
    sub.mute = sorted(words)
    await session.commit()
    return sub.mute


async def remove_subscriber_mute(
    session: AsyncSession, chat_id: str, keyword: str
) -> List[str]:
    kw = keyword.strip().lower()
    sub = await session.get(TelegramSubscriber, chat_id)
    if sub is None:
        return []
    sub.mute = [w for w in (sub.mute or []) if w != kw]
    await session.commit()
    return sub.mute


async def latest_news(
    session: AsyncSession, limit: int = 10
) -> List[Dict[str, Any]]:
    """Most recent cached news across all sources."""
    rows = (
        await session.execute(
            select(NewsRow).order_by(NewsRow.published_at.desc()).limit(limit)
        )
    ).scalars().all()
    return [
        {
            "title": r.title,
            "source": r.source,
            "url": r.url,
            "tickers": list(r.tickers or []),
            "importance": r.importance,
        }
        for r in rows
    ]


async def add_subscriber_keyword(
    session: AsyncSession, chat_id: str, keyword: str
) -> List[str]:
    kw = keyword.strip().lower()
    sub = await session.get(TelegramSubscriber, chat_id)
    if sub is None:
        sub = TelegramSubscriber(chat_id=chat_id, tickers=[], keywords=[])
        session.add(sub)
    words = list(sub.keywords or [])
    if kw and kw not in words:
        words.append(kw)
    sub.keywords = sorted(words)
    await session.commit()
    return sub.keywords


async def remove_subscriber_keyword(
    session: AsyncSession, chat_id: str, keyword: str
) -> List[str]:
    kw = keyword.strip().lower()
    sub = await session.get(TelegramSubscriber, chat_id)
    if sub is None:
        return []
    sub.keywords = [w for w in (sub.keywords or []) if w != kw]
    await session.commit()
    return sub.keywords


async def set_subscriber_all_news(
    session: AsyncSession, chat_id: str, on: bool
) -> None:
    sub = await session.get(TelegramSubscriber, chat_id)
    if sub is None:
        sub = TelegramSubscriber(chat_id=chat_id, tickers=[], keywords=[])
        session.add(sub)
    sub.all_news = on
    await session.commit()


async def set_subscriber_high_only(
    session: AsyncSession, chat_id: str, on: bool
) -> None:
    sub = await session.get(TelegramSubscriber, chat_id)
    if sub is None:
        sub = TelegramSubscriber(chat_id=chat_id, tickers=[], keywords=[])
        session.add(sub)
    sub.high_only = on
    await session.commit()


async def link_subscriber(
    session: AsyncSession, chat_id: str, link_token: str, tickers: List[str]
) -> None:
    """Attach a persistent link token + set the watchlist from the app."""
    sub = await session.get(TelegramSubscriber, chat_id)
    if sub is None:
        sub = TelegramSubscriber(chat_id=chat_id, tickers=[])
        session.add(sub)
    sub.link_token = link_token
    sub.tickers = sorted({t.upper() for t in tickers})
    await session.commit()


async def sync_subscriber_by_token(
    session: AsyncSession, link_token: str, tickers: List[str]
) -> bool:
    row = (
        await session.execute(
            select(TelegramSubscriber).where(
                TelegramSubscriber.link_token == link_token
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return False
    row.tickers = sorted({t.upper() for t in tickers})
    await session.commit()
    return True


async def get_subscriber_by_token(
    session: AsyncSession, link_token: str
) -> Optional[Dict[str, Any]]:
    row = (
        await session.execute(
            select(TelegramSubscriber).where(
                TelegramSubscriber.link_token == link_token
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return _subscriber_dict(row)


def _subscriber_dict(row: TelegramSubscriber) -> Dict[str, Any]:
    """Single serialisation point so every endpoint returns the same shape."""
    return {
        "chat_id": row.chat_id,
        "tickers": list(row.tickers or []),
        "keywords": list(row.keywords or []),
        "mute": list(row.mute or []),
        "all_news": bool(row.all_news),
        "high_only": bool(row.high_only),
        # Control-panel filters. `sources: []` means "all sources", not "none".
        "news_alerts": bool(getattr(row, "news_alerts", True)),
        "stockpick_alerts": bool(getattr(row, "stockpick_alerts", False)),
        "sources": list(getattr(row, "sources", None) or []),
        "min_rsi": int(getattr(row, "min_rsi", 100) or 100),
    }


async def set_prefs_by_token(
    session: AsyncSession,
    link_token: str,
    all_news: Optional[bool] = None,
    mute: Optional[List[str]] = None,
    high_only: Optional[bool] = None,
    news_alerts: Optional[bool] = None,
    stockpick_alerts: Optional[bool] = None,
    sources: Optional[List[str]] = None,
    min_rsi: Optional[int] = None,
    tickers: Optional[List[str]] = None,
    keywords: Optional[List[str]] = None,
) -> bool:
    """
    Patch semantics: only non-None fields are written, so the app can send a
    single toggle without clobbering the rest of the subscriber's settings.
    """
    row = (
        await session.execute(
            select(TelegramSubscriber).where(
                TelegramSubscriber.link_token == link_token
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return False
    if all_news is not None:
        row.all_news = bool(all_news)
    if mute is not None:
        row.mute = sorted({m.strip().lower() for m in mute if m.strip()})
    if high_only is not None:
        row.high_only = bool(high_only)
    if news_alerts is not None:
        row.news_alerts = bool(news_alerts)
    if stockpick_alerts is not None:
        row.stockpick_alerts = bool(stockpick_alerts)
    if sources is not None:
        # Reassign (don't mutate) so SQLAlchemy tracks the JSON change.
        row.sources = sorted({s.strip() for s in sources if s.strip()})
    if min_rsi is not None:
        row.min_rsi = max(0, min(100, int(min_rsi)))
    if tickers is not None:
        row.tickers = sorted({t.strip().upper() for t in tickers if t.strip()})
    if keywords is not None:
        row.keywords = sorted({k.strip().lower() for k in keywords if k.strip()})
    await session.commit()
    return True


async def latest_news_for_tickers(
    session: AsyncSession, tickers: List[str], limit: int = 5
) -> List[Dict[str, Any]]:
    """Most recent cached news whose tickers overlap the given set."""
    tset = {t.upper() for t in tickers}
    if not tset:
        return []
    rows = (
        await session.execute(
            select(NewsRow).order_by(NewsRow.published_at.desc()).limit(300)
        )
    ).scalars().all()
    out: List[Dict[str, Any]] = []
    for r in rows:
        if tset.intersection(r.tickers or []):
            out.append(
                {
                    "title": r.title,
                    "source": r.source,
                    "url": r.url,
                    "tickers": list(r.tickers or []),
                    "importance": r.importance,
                }
            )
            if len(out) >= limit:
                break
    return out


# ── Commodity prices ─────────────────────────────────────────────────────────

async def insert_commodity_prices(
    session: AsyncSession, quotes: List[Dict[str, Any]]
) -> int:
    """
    Append timestamped price observations. Callers pass only prices that
    actually moved — this is an append-only history table, not an upsert.
    """
    if not quotes:
        return 0
    for q in quotes:
        session.add(CommodityPriceRow(
            symbol=q["symbol"],
            name=q["name"],
            price=q["price"],
            currency=q.get("currency", "USD"),
            change=q.get("change"),
            change_percent=q.get("changePercent"),
            is_proxy=bool(q.get("isProxy", False)),
        ))
    await session.commit()
    logger.debug("repo.commodity_insert count=%d", len(quotes))
    return len(quotes)


async def latest_commodity_prices(session: AsyncSession) -> List[Dict[str, Any]]:
    """Most recent observation per symbol."""
    rows = (
        await session.execute(
            select(CommodityPriceRow).order_by(CommodityPriceRow.recorded_at.desc()).limit(500)
        )
    ).scalars().all()

    seen: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        if r.symbol in seen:
            continue
        seen[r.symbol] = {
            "symbol": r.symbol,
            "name": r.name,
            "price": r.price,
            "currency": r.currency,
            "change": r.change,
            "changePercent": r.change_percent,
            "isProxy": r.is_proxy,
            "recordedAt": r.recorded_at.isoformat() if r.recorded_at else None,
        }
    return list(seen.values())


async def commodity_history(
    session: AsyncSession, symbol: str, limit: int = 200
) -> List[Dict[str, Any]]:
    """Timestamped price history for one symbol, newest first."""
    rows = (
        await session.execute(
            select(CommodityPriceRow)
            .where(CommodityPriceRow.symbol == symbol)
            .order_by(CommodityPriceRow.recorded_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [
        {
            "price": r.price,
            "change": r.change,
            "changePercent": r.change_percent,
            "recordedAt": r.recorded_at.isoformat() if r.recorded_at else None,
        }
        for r in rows
    ]


async def backfill_msci_flags(session: AsyncSession) -> int:
    """
    Classify cached news that predates the MSCI columns.

    New items are flagged at insert time, so this only matters once — without
    it, MSCI articles already in the cache stay silently unflagged and the app
    shows them as ordinary news. Only rows that MATCH are written, so a second
    run is a no-op rather than a full table rewrite.
    """
    rows = (
        await session.execute(
            select(NewsRow).where(NewsRow.is_msci_alert.is_(False))
        )
    ).scalars().all()

    updated = 0
    for row in rows:
        if classify_msci(row.title or "", row.excerpt or "")["is_msci_alert"]:
            row.is_msci_alert = True
            row.priority = "HIGH"
            updated += 1

    if updated:
        await session.commit()
    logger.info("repo.msci_backfill scanned=%d flagged=%d", len(rows), updated)
    return updated


async def backfill_tickers(session: AsyncSession) -> int:
    """
    Re-run ticker detection over cached news that has none.

    Detection is applied at insert time, so articles stored before a company
    name was added to TICKER_KEYWORDS keep an empty ticker list forever — and
    stay invisible to watchlist alerts and the volume/news linkage. Only rows
    that gain a ticker are written, so repeat runs are no-ops.

    Deliberately does NOT revisit rows that already have tickers: re-detection
    could only remove one, and silently un-tagging an article that already
    triggered an alert would be worse than leaving it.
    """
    from backend.services.ticker_service import detect_tickers

    rows = (
        await session.execute(
            select(NewsRow).where(NewsRow.tickers == [])
        )
    ).scalars().all()

    updated = 0
    for row in rows:
        found = detect_tickers(f"{row.title or ''} {row.excerpt or ''}")
        if found:
            row.tickers = found
            updated += 1

    if updated:
        await session.commit()
    logger.info("repo.ticker_backfill scanned=%d tagged=%d", len(rows), updated)
    return updated
