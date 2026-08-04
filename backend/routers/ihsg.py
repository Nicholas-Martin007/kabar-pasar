"""
IHSG market prospect API.

    GET /api/v1/market/ihsg-overview   -> technicals, macro catalysts, prospect
    GET /api/v1/market/msci-calendar   -> upcoming MSCI index reviews

Both are read-only views over cached computation; neither triggers a write.
"""

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query

from backend.services.ihsg_engine import build_ihsg_overview
from scrapers.msci_tracker import calendar_snapshot

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/market", tags=["ihsg"])


@router.get("/ihsg-overview")
async def ihsg_overview(
    force: bool = Query(False, description="Bypass the 10-minute cache"),
) -> Dict[str, Any]:
    """
    Daily IHSG overview: status, key levels, technicals, macro catalysts and a
    plain-language prospect summary.

    `foreign_flow_available` is false and carries a reason — aggregate IDX
    foreign net buy/sell has no free source, and the field is left empty rather
    than estimated.
    """
    try:
        overview = await build_ihsg_overview(force=force)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("ihsg.overview_failed")
        raise HTTPException(
            status_code=502, detail=f"IHSG overview failed: {exc}"
        ) from exc

    payload = overview.to_dict()
    payload["msci"] = calendar_snapshot()
    return payload


@router.get("/msci-calendar")
async def msci_calendar() -> Dict[str, Any]:
    """Scheduled MSCI index reviews and the next one due."""
    return calendar_snapshot()
