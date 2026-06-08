"""
Investor.id — light HTML scraper (no RSS available).

Scrapes section listing pages for article links. Fragile by nature: if the site
markup changes, selectors may need updating. Only headlines + links are taken
(no full-article reproduction).
"""

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import List

import httpx
from bs4 import BeautifulSoup

from models.news import News, NewsSource
from services.ticker_service import detect_tickers

from .base import guess_category, score_importance, stable_id

logger = logging.getLogger(__name__)

BASE = "https://investor.id"
SECTIONS = ["/market", "/stock", "/corporate-action"]
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
# Article hrefs look like: /<section>/<id>/<slug>
_HREF_RE = re.compile(
    r"^/(market|stock|corporate-action|bond|crypto|macroeconomics|economy)/\d+/"
)


async def _fetch_section(url: str) -> List[News]:
    try:
        async with httpx.AsyncClient(
            timeout=15, follow_redirects=True, headers=_UA
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
        soup = await asyncio.to_thread(BeautifulSoup, resp.text, "html.parser")
    except Exception as exc:
        logger.warning("scrape.failed source=Investor.id url=%s error=%s", url, exc)
        return []

    items: List[News] = []
    seen: set = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not _HREF_RE.match(href):
            continue
        # Strip leading rank digits some widgets prepend (e.g. "2Nilai Tukar...").
        title = re.sub(r"^\d+\s*", "", a.get_text(strip=True)).strip()
        if len(title) < 25:
            continue
        full = BASE + href
        if full in seen:
            continue
        seen.add(full)
        items.append(
            News(
                id=stable_id(full),
                title=title,
                source=NewsSource.INVESTOR_ID,
                published_at=datetime.now(timezone.utc).isoformat(),
                excerpt=title,
                ai_summary=[],
                tickers=detect_tickers(title),
                importance=score_importance(title, ""),
                category=guess_category(title, ""),
                url=full,
            )
        )
    return items


async def fetch() -> List[News]:
    results = await asyncio.gather(
        *[_fetch_section(BASE + s) for s in SECTIONS], return_exceptions=True
    )
    out: List[News] = []
    seen: set = set()
    for r in results:
        if isinstance(r, list):
            for n in r:
                if n.id not in seen:
                    seen.add(n.id)
                    out.append(n)
    logger.info("scrape.fetched source=Investor.id count=%d", len(out))
    return out
