"""Kontan — investasi / pasar modal RSS."""

from typing import List

from models.news import News, NewsSource

from .base import fetch_rss

FEED_URLS = (
    "https://rss.kontan.co.id/action/rss/Kontan",
    "https://investasi.kontan.co.id/rss",
)


async def fetch() -> List[News]:
    for url in FEED_URLS:
        items = await fetch_rss(NewsSource.KONTAN, url)
        if items:
            return items
    return []
