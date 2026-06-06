"""CNBC Indonesia — market section RSS."""

from typing import List

from models.news import News, NewsSource

from .base import fetch_rss

FEED_URL = "https://www.cnbcindonesia.com/rss/market.rss"


async def fetch() -> List[News]:
    return await fetch_rss(NewsSource.CNBC_INDONESIA, FEED_URL)
