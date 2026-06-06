"""
News API — reads cached results from SQLite (fast).
Live fetch + AI happens in the background scheduler; trigger a one-shot
refresh via POST /refresh.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from db.repository import count_news, query_news
from db.session import get_session
from models.news import News, NewsImportance, NewsSource
from services.scheduler import refresh_news_job

logger = logging.getLogger(__name__)

router = APIRouter(tags=["news"])


@router.get("/news", response_model=List[News])
async def get_news(
    limit:      int                      = Query(50, ge=1, le=200),
    source:     Optional[NewsSource]     = Query(None, description="Filter by source"),
    importance: Optional[NewsImportance] = Query(None, description="high / medium / low"),
    ticker:     Optional[str]            = Query(None, description="e.g. BBCA"),
) -> JSONResponse:
    """
    Read cached news sorted by published_at desc.
    Filters: ?source=BEI&importance=high&ticker=BBRI
    """
    try:
        async with get_session() as session:
            items = await query_news(
                session,
                source=source.value if source else None,
                importance=importance.value if importance else None,
                ticker=ticker,
                limit=limit,
            )
    except Exception as exc:
        logger.exception("news.query_failed")
        raise HTTPException(status_code=500, detail=f"DB read error: {exc}")

    return JSONResponse(content=[n.model_dump(by_alias=True) for n in items])


@router.post("/refresh", tags=["meta"])
async def trigger_refresh() -> dict:
    """
    Manually trigger a fetch + summarise cycle. Awaits completion so the
    response includes counts. Use for testing or after editing source list.
    """
    try:
        result = await refresh_news_job()
    except Exception as exc:
        logger.exception("refresh.failed")
        raise HTTPException(status_code=502, detail=f"Refresh error: {exc}")
    return {"status": "ok", **result}


@router.get("/news/stats", tags=["meta"])
async def news_stats() -> dict:
    """Quick health probe: how many items are cached?"""
    async with get_session() as session:
        total = await count_news(session)
    return {"cached_news_count": total}
