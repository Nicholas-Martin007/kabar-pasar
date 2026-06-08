"""Yahoo Finance — global markets + commodities (incl. a dedicated gold feed)."""

import asyncio
from typing import List

from models.news import News, NewsSource

from .base import fetch_rss

FEEDS = [
    "https://finance.yahoo.com/news/rssindex",  # top markets/finance
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=GC=F&region=US&lang=en-US",  # gold
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=CL=F&region=US&lang=en-US",  # crude oil
]


async def fetch() -> List[News]:
    results = await asyncio.gather(
        *[fetch_rss(NewsSource.YAHOO_FINANCE, url) for url in FEEDS],
        return_exceptions=True,
    )
    out: List[News] = []
    for r in results:
        if isinstance(r, list):
            out.extend(r)
    return out
