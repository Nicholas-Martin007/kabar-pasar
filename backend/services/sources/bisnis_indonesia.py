"""Bisnis Indonesia — market section RSS."""

from typing import List

from models.news import News, NewsSource

from .base import fetch_rss

FEED_URLS = (
    "https://bisnis.com/rss/pasar-modal.rss",
    "https://market.bisnis.com/rss",
)


async def fetch() -> List[News]:
    for url in FEED_URLS:
        items = await fetch_rss(NewsSource.BISNIS_INDONESIA, url)
        if items:
            return items
    return []
