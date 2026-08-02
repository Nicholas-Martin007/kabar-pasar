"""CNBC Indonesia — market section RSS."""

from typing import List

from backend.models.news import News, NewsSource

from .base import fetch_rss

# NOTE: the old "/rss/market.rss" path now 404s — this source was silently
# returning zero items. Verified 2026-08-02: this URL serves 100 entries and,
# unlike the other feeds, sends Last-Modified + Cache-Control: max-age=30, so
# the fast poller can use conditional GET against it.
FEED_URL = "https://www.cnbcindonesia.com/market/rss"


async def fetch() -> List[News]:
    return await fetch_rss(NewsSource.CNBC_INDONESIA, FEED_URL)
