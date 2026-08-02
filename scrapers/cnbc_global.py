"""CNBC Global — world geopolitics + economy (Trump, Iran, war, Fed, macro)."""

import asyncio
from typing import List

from backend.models.news import News, NewsSource

from .base import fetch_rss

FEEDS = [
    "https://www.cnbc.com/id/100727362/device/rss/rss.html",   # World news
    "https://www.cnbc.com/id/20910258/device/rss/rss.html",    # Economy
    "https://www.cnbc.com/id/15839069/device/rss/rss.html",    # Markets
]


async def fetch() -> List[News]:
    results = await asyncio.gather(
        *[fetch_rss(NewsSource.CNBC_GLOBAL, url) for url in FEEDS],
        return_exceptions=True,
    )
    out: List[News] = []
    for r in results:
        if isinstance(r, list):
            out.extend(r)
    return out
