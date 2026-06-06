"""Detik Finance — finance RSS."""

from typing import List

from models.news import News, NewsSource

from .base import fetch_rss

# Detik historically rotates between paths; primary then fallback.
FEED_URLS = (
    "https://rss.detik.com/index.php/finance",
    "https://finance.detik.com/rss",
)


async def fetch() -> List[News]:
    for url in FEED_URLS:
        items = await fetch_rss(NewsSource.DETIK_FINANCE, url)
        if items:
            return items
    return []
