"""Katadata — data-driven Indonesian business & economy news."""

from typing import List

from models.news import News, NewsSource

from .base import fetch_rss

FEED_URL = "https://katadata.co.id/rss"


async def fetch() -> List[News]:
    return await fetch_rss(NewsSource.KATADATA, FEED_URL)
