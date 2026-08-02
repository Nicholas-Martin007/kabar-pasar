"""Kontan — investasi / pasar modal RSS."""

from typing import List

from backend.models.news import News, NewsSource

from .base import fetch_rss

# Working feed first — `fetch()` returns on the first non-empty result, and the
# fast poller takes FEED_URLS[0]. Verified 2026-08-02: investasi.kontan.co.id
# serves 25 entries; rss.kontan.co.id fails the TLS handshake and
# www.kontan.co.id/rss parses to 0 entries, so it is a fallback only.
FEED_URLS = (
    "https://investasi.kontan.co.id/rss",
    "https://rss.kontan.co.id/action/rss/Kontan",
)


async def fetch() -> List[News]:
    for url in FEED_URLS:
        items = await fetch_rss(NewsSource.KONTAN, url)
        if items:
            return items
    return []
