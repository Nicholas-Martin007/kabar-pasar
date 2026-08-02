"""
Data-access helpers — keep SQL out of services & routers.

`upsert_news_items` returns IDs of *newly* inserted rows so the scheduler
knows which items need AI summarisation.
"""

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models.news import News, NewsCategory, NewsImportance, NewsSource

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
    )


# ── Writes ────────────────────────────────────────────────────────────────────

async def upsert_news_items(session: AsyncSession, items: List[News]) -> List[News]:
    """Insert news rows that don't exist yet. Returns the NEW items only."""
    if not items:
        return []

    ids = [n.id for n in items]
    existing_ids = set(
        (await session.execute(select(NewsRow.id).where(NewsRow.id.in_(ids))))
        .scalars()
        .all()
    )

    new_items = [n for n in items if n.id not in existing_ids]
    for item in new_items:
        session.add(NewsRow(
            id=item.id,
            title=item.title,
            source=item.source.value,
            published_at=item.published_at,
            excerpt=item.excerpt,
            tickers=item.tickers,
            importance=item.importance.value,
            category=item.category.value,
            url=item.url,
        ))
    await session.commit()
    logger.info(
        "repo.upsert total=%d existing=%d new=%d",
        len(items), len(existing_ids), len(new_items),
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
    stmt = stmt.limit(limit)

    rows = (await session.execute(stmt)).scalars().all()
    items = [_row_to_news(r) for r in rows]

    if ticker:
        ticker = ticker.upper()
        items = [n for n in items if ticker in n.tickers]
    return items


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
    return [
        {
            "chat_id": r.chat_id,
            "tickers": list(r.tickers or []),
            "keywords": list(r.keywords or []),
            "mute": list(r.mute or []),
            "all_news": bool(r.all_news),
            "high_only": bool(r.high_only),
        }
        for r in rows
    ]


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
    return {
        "chat_id": row.chat_id,
        "tickers": list(row.tickers or []),
        "keywords": list(row.keywords or []),
        "mute": list(row.mute or []),
        "all_news": bool(row.all_news),
        "high_only": bool(row.high_only),
    }


async def set_prefs_by_token(
    session: AsyncSession,
    link_token: str,
    all_news: Optional[bool] = None,
    mute: Optional[List[str]] = None,
    high_only: Optional[bool] = None,
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
    if all_news is not None:
        row.all_news = bool(all_news)
    if mute is not None:
        row.mute = sorted({m.strip().lower() for m in mute if m.strip()})
    if high_only is not None:
        row.high_only = bool(high_only)
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
