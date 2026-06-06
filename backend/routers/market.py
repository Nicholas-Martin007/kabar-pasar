"""Market data API — live quotes & charts from Yahoo Finance (IDX .JK / ^JKSE)."""

import logging

from fastapi import APIRouter, HTTPException, Query

from services.market_service import (
    IHSG_SYMBOL,
    RANGE_INTERVAL,
    fetch_quote,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/index")
async def market_index() -> dict:
    """IHSG (Jakarta Composite Index) quote."""
    try:
        return await fetch_quote(IHSG_SYMBOL)
    except Exception as exc:
        logger.warning("market.index_failed error=%s", exc)
        raise HTTPException(status_code=502, detail=f"Market data error: {exc}")


@router.get("/quote/{ticker}")
async def market_quote(ticker: str) -> dict:
    """Quote for a single IDX stock, e.g. /market/quote/BBCA."""
    try:
        return await fetch_quote(ticker)
    except Exception as exc:
        logger.warning("market.quote_failed ticker=%s error=%s", ticker, exc)
        raise HTTPException(status_code=502, detail=f"Market data error: {exc}")


@router.get("/chart/{ticker}")
async def market_chart(
    ticker: str,
    range: str = Query("1M", description="1H | 1D | 1W | 1M | 1Y"),
) -> dict:
    """Sparkline/price points for a ticker over a time range."""
    rng = range.upper()
    yahoo_range, interval = RANGE_INTERVAL.get(rng, ("1mo", "1d"))
    try:
        quote = await fetch_quote(ticker, range_=yahoo_range, interval=interval)
        return {
            "ticker": quote["ticker"],
            "range": rng,
            "currency": quote["currency"],
            "points": quote["sparkline"],
        }
    except Exception as exc:
        logger.warning("market.chart_failed ticker=%s error=%s", ticker, exc)
        raise HTTPException(status_code=502, detail=f"Market data error: {exc}")
