"""Market data API — live quotes & charts from Yahoo Finance (IDX .JK / ^JKSE)."""

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from services.market_service import (
    IHSG_SYMBOL,
    RANGE_INTERVAL,
    fetch_chart_data,
    fetch_quote,
    fetch_quotes,
    fetch_reaction,
    fetch_reactions,
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


@router.get("/quotes")
async def market_quotes(
    tickers: str = Query(..., description="Comma-separated tickers, e.g. BBCA,BBRI"),
) -> dict:
    """Batched live quotes for a watchlist (one request)."""
    syms = [t for t in tickers.split(",") if t.strip()][:50]
    try:
        return {"quotes": await fetch_quotes(syms)}
    except Exception as exc:
        logger.warning("market.quotes_failed error=%s", exc)
        raise HTTPException(status_code=502, detail=f"Market data error: {exc}")


@router.get("/chart/{ticker}")
async def market_chart(
    ticker: str,
    range: str = Query("1M", description="1H | 1D | 1W | 1M | 1Y"),
) -> dict:
    """Line points + OHLC candles for a ticker over a time range."""
    rng = range.upper()
    yahoo_range, interval = RANGE_INTERVAL.get(rng, ("1mo", "1d"))
    try:
        data = await fetch_chart_data(ticker, yahoo_range, interval)
        return {
            "ticker": ticker.strip().upper(),
            "range": rng,
            "currency": data["currency"],
            "points": data["points"],
            "candles": data["candles"],
        }
    except Exception as exc:
        logger.warning("market.chart_failed ticker=%s error=%s", ticker, exc)
        raise HTTPException(status_code=502, detail=f"Market data error: {exc}")


@router.get("/reaction/{ticker}")
async def market_reaction(
    ticker: str,
    at: str = Query(..., description="News timestamp, ISO 8601"),
    window: int = Query(60, ge=5, le=480, description="Window in minutes"),
) -> dict:
    """How the stock moved in the window after a news item was published."""
    try:
        return await fetch_reaction(ticker, at, window_min=window)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.warning("market.reaction_failed ticker=%s error=%s", ticker, exc)
        raise HTTPException(status_code=502, detail=f"Market data error: {exc}")


class ReactionItem(BaseModel):
    key: Optional[str] = None  # echoed back so the caller can map rows
    ticker: str
    at: str
    window: int = Field(60, ge=5, le=480)


class ReactionBatchRequest(BaseModel):
    items: List[ReactionItem] = Field(..., max_length=60)


@router.post("/reactions")
async def market_reactions(body: ReactionBatchRequest) -> dict:
    """Batched reaction lookup — one request for many feed cards."""
    try:
        results = await fetch_reactions([i.model_dump() for i in body.items])
        return {"reactions": results}
    except Exception as exc:
        logger.warning("market.reactions_failed error=%s", exc)
        raise HTTPException(status_code=502, detail=f"Market data error: {exc}")
