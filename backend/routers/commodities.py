"""
Commodity price endpoints.

`isProxy: true` means the row is an Indonesian miner's share price standing in
for a commodity with no free Yahoo futures contract (coal, nickel) — not a spot
price. Clients must label those differently; see scrapers/commodity_tracker.py.
"""

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query

from backend.db.repository import commodity_history, latest_commodity_prices
from backend.db.session import get_session
from scrapers.commodity_tracker import BASKET

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/commodities", tags=["commodities"])


@router.get("")
async def list_commodities() -> Dict[str, Any]:
    """Latest observed price per tracked symbol."""
    async with get_session() as session:
        quotes = await latest_commodity_prices(session)
    return {
        "items": quotes,
        "tracked": [
            {
                "symbol": c.symbol,
                "name": c.name,
                "currency": c.currency,
                "isProxy": c.is_proxy,
            }
            for c in BASKET
        ],
    }


@router.get("/{symbol}/history")
async def get_commodity_history(
    symbol: str, limit: int = Query(200, ge=1, le=2000)
) -> Dict[str, Any]:
    """Timestamped price history for one symbol, newest first."""
    known = {c.symbol: c for c in BASKET}
    meta = known.get(symbol)
    if meta is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown symbol '{symbol}'. Tracked: {sorted(known)}",
        )

    async with get_session() as session:
        points: List[Dict[str, Any]] = await commodity_history(session, symbol, limit)

    return {
        "symbol": symbol,
        "name": meta.name,
        "currency": meta.currency,
        "isProxy": meta.is_proxy,
        "points": points,
    }
