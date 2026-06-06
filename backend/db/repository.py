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

from models.news import News, NewsCategory, NewsImportance, NewsSource

from .models import AISummaryRow, NewsRow

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
