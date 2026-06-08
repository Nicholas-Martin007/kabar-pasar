"""Liputan6 — Indonesian business & stock-market news."""

import asyncio
from typing import List

from models.news import News, NewsSource

from .base import fetch_rss

FEEDS = [
    "https://feed.liputan6.com/rss/bisnis",
    "https://feed.liputan6.com/rss/saham",
]


async def fetch() -> List[News]:
    results = await asyncio.gather(
        *[fetch_rss(NewsSource.LIPUTAN6, url) for url in FEEDS],
        return_exceptions=True,
    )
    out: List[News] = []
    for r in results:
        if isinstance(r, list):
            out.extend(r)
    return out
