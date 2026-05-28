import os
from typing import List

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from models.news import News
from services.ai_summarizer import enrich_with_summaries
from services.rss_service import fetch_all_news

router = APIRouter(prefix="/news", tags=["news"])

# How many items get AI summaries per request (cost control)
_AI_BATCH = int(os.getenv("AI_SUMMARY_BATCH", "10"))


@router.get("", response_model=List[News])
async def get_news(
    limit: int = Query(default=50, ge=1, le=200, description="Max items to return"),
    ticker: str = Query(default=None, description="Filter by ticker (e.g. BBCA)"),
) -> JSONResponse:
    """
    Fetch and return parsed news from all RSS sources.
    Results are sorted by published_at descending.
    Top AI_SUMMARY_BATCH items (default 10) are enriched with AI-generated bullets.
    """
    try:
        items = fetch_all_news()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Feed fetch error: {exc}")

    if ticker:
        items = [n for n in items if ticker.upper() in n.tickers]

    items = items[:limit]

    try:
        items = await enrich_with_summaries(items, limit=_AI_BATCH)
    except Exception as exc:
        # AI enrichment is best-effort — never block news delivery
        pass

    return JSONResponse(content=[n.model_dump(by_alias=True) for n in items])
