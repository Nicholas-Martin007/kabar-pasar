"""
Technical-analysis chart API.

    GET /api/v1/charts/{ticker}          -> JSON levels + imageUrl
    GET /api/v1/charts/{ticker}/image    -> the PNG itself

Levels are mechanical arithmetic on historical prices, not advice; every
response carries `disclaimer` and `warnings`, and the disclaimer is also burned
into the image.
"""

import logging
import re
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from backend.services.chart_service import get_chart, get_chart_with_rationale

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/charts", tags=["charts"])

# Yahoo symbols: letters/digits, optional .SUFFIX or ^INDEX. Anchored so a
# crafted value can't walk out of the charts directory when it becomes a
# filename downstream.
_TICKER_RE = re.compile(r"^\^?[A-Za-z0-9]{1,12}(\.[A-Za-z]{1,4})?$")


def _validate(ticker: str) -> str:
    t = ticker.strip().upper()
    if not _TICKER_RE.match(t):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid ticker '{ticker}'. Expected e.g. BBCA.JK, AAPL, ^JKSE.",
        )
    return t


@router.get("/{ticker}")
async def chart_json(
    ticker: str,
    force: bool = Query(False, description="Bypass the 5-minute cache and re-render"),
    rationale: bool = Query(True, description="Include the plain-language summary"),
) -> Dict[str, Any]:
    """TA levels for `ticker`, plus a URL for the rendered PNG."""
    symbol = _validate(ticker)
    try:
        if rationale:
            result, text = await get_chart_with_rationale(symbol, force=force)
        else:
            result, text = await get_chart(symbol, force=force), None
    except ValueError as exc:
        # Unknown symbol / not enough history — the client's problem, not ours.
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("chart.failed ticker=%s", symbol)
        raise HTTPException(
            status_code=502, detail=f"Chart generation failed: {exc}"
        ) from exc

    payload = result.to_dict()
    # Serve the image through the API rather than leaking a filesystem path.
    payload["imageUrl"] = f"/api/v1/charts/{symbol}/image"
    payload.pop("chart_path", None)
    if text is not None:
        payload["rationale"] = text
    return payload


@router.get("/{ticker}/image")
async def chart_image(
    ticker: str,
    force: bool = Query(False, description="Bypass the 5-minute cache and re-render"),
) -> FileResponse:
    """The rendered PNG. Generates it first if the cache is cold."""
    symbol = _validate(ticker)
    try:
        result = await get_chart(symbol, force=force)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("chart.image_failed ticker=%s", symbol)
        raise HTTPException(
            status_code=502, detail=f"Chart generation failed: {exc}"
        ) from exc

    path = Path(result.chart_path)
    if not path.is_file():
        # Cached result but the file was cleaned up underneath us — re-render once.
        result = await get_chart(symbol, force=True)
        path = Path(result.chart_path)
        if not path.is_file():
            raise HTTPException(status_code=500, detail="Chart image missing after render")

    return FileResponse(
        path,
        media_type="image/png",
        filename=path.name,
        # Match the service-side cache so clients don't re-request every second.
        headers={"Cache-Control": "public, max-age=300"},
    )
