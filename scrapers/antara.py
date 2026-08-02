"""Antara — Indonesian national news agency (economy + latest)."""

import asyncio
from typing import List

from backend.models.news import News, NewsSource

from .base import fetch_rss

FEEDS = [
    "https://www.antaranews.com/rss/ekonomi.xml",
    "https://www.antaranews.com/rss/terkini.xml",
]


async def fetch() -> List[News]:
    results = await asyncio.gather(
        *[fetch_rss(NewsSource.ANTARA, url) for url in FEEDS],
        return_exceptions=True,
    )
    out: List[News] = []
    for r in results:
        if isinstance(r, list):
            out.extend(r)
    return out
