"""Bloomberg Technoz — economy & markets RSS (IDX-focused)."""

from typing import List

from backend.models.news import News, NewsSource

from .base import fetch_rss

FEED_URL = "https://www.bloombergtechnoz.com/rss"


async def fetch() -> List[News]:
    return await fetch_rss(NewsSource.BLOOMBERG_TECHNOZ, FEED_URL)
