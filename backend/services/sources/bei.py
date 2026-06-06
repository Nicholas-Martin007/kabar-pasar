"""
BEI (IDX) announcements scraper.

IDX publishes corporate announcements at /en/news/announcements/. Page renders
client-side from a JSON API; we try the API first (more stable) then fall back
to HTML scraping with BeautifulSoup.

Throttle: minimum 5 minutes between successful fetches to respect IDX.
Failure mode: log warning, return [] — never crash the aggregator.

NOTE: Before production use, verify robots.txt and ToS at https://www.idx.co.id/
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import List

import httpx
from bs4 import BeautifulSoup

from models.news import News, NewsCategory, NewsImportance, NewsSource

from .base import stable_id

logger = logging.getLogger(__name__)

# Public IDX announcements API used by the website itself
_API_URL = "https://www.idx.co.id/primary/NewsAnnouncement/GetAnnouncement"
_HTML_URL = "https://www.idx.co.id/en/news/announcements/"
_TIMEOUT = 12
_USER_AGENT = (
    "Mozilla/5.0 (compatible; KabarPasar/0.1; +contact via Anthropic Claude)"
)

# 5-minute throttle as required by spec
_MIN_INTERVAL_SEC = 5 * 60
_last_fetch_ts: float = 0.0


def _is_corporate_action(title: str) -> bool:
    text = title.lower()
    keywords = (
        "dividen", "rups", "rights issue", "buyback", "akuisisi", "merger",
        "spin-off", "stock split", "obligasi", "tender offer",
        "dividend", "acquisition", "share buyback",
    )
    return any(k in text for k in keywords)


def _parse_iso(date_str: str) -> str:
    try:
        # IDX timestamps vary: "2026-05-30T14:30:00" or "30 May 2026 14:30"
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d %b %Y %H:%M"):
            try:
                return datetime.strptime(date_str.strip(), fmt).replace(
                    tzinfo=timezone.utc
                ).isoformat()
            except ValueError:
                continue
    except Exception:
        pass
    return datetime.now(timezone.utc).isoformat()


async def _fetch_via_api(client: httpx.AsyncClient) -> List[News]:
    """Try the JSON endpoint that powers the IDX announcements page."""
    params = {
        "indexFrom": 1,
        "pageSize": 30,
        "dateFrom": "",
        "dateTo": "",
        "lang": "id",
        "keyword": "",
    }
    resp = await client.get(_API_URL, params=params)
    resp.raise_for_status()
    data = resp.json()
    rows = data.get("Items") or data.get("data") or []

    items: List[News] = []
    for row in rows:
        title = (row.get("JudulPengumuman") or row.get("Title") or "").strip()
        if not title:
            continue
        link = row.get("FileLink") or row.get("Url") or _HTML_URL
        published = row.get("TglPengumuman") or row.get("PublishedDate") or ""
        items.append(
            News(
                id=stable_id(link, str(row.get("Id", ""))),
                title=title,
                source=NewsSource.BEI,
                published_at=_parse_iso(published) if published else
                              datetime.now(timezone.utc).isoformat(),
                excerpt=title,  # IDX listing only gives title; full PDF behind link
                ai_summary=[],
                tickers=[],
                importance=NewsImportance.HIGH if _is_corporate_action(title)
                            else NewsImportance.MEDIUM,
                category=NewsCategory.CORPORATE_ACTION if _is_corporate_action(title)
                          else NewsCategory.REGULATORY,
                url=link,
            )
        )
    return items


async def _fetch_via_html(client: httpx.AsyncClient) -> List[News]:
    """Fallback: scrape the HTML page (may break if IDX changes markup)."""
    resp = await client.get(_HTML_URL)
    resp.raise_for_status()
    soup = await asyncio.to_thread(BeautifulSoup, resp.text, "html.parser")

    items: List[News] = []
    # IDX uses <tr> rows with announcement links; selector is best-effort
    for row in soup.select("table tr, .announcement-item, .card"):
        link_tag = row.find("a", href=True)
        if not link_tag:
            continue
        title = link_tag.get_text(strip=True)
        if not title or len(title) < 10:
            continue
        href = link_tag["href"]
        if href.startswith("/"):
            href = "https://www.idx.co.id" + href
        items.append(
            News(
                id=stable_id(href),
                title=title,
                source=NewsSource.BEI,
                published_at=datetime.now(timezone.utc).isoformat(),
                excerpt=title,
                ai_summary=[],
                tickers=[],
                importance=NewsImportance.HIGH if _is_corporate_action(title)
                            else NewsImportance.MEDIUM,
                category=NewsCategory.CORPORATE_ACTION if _is_corporate_action(title)
                          else NewsCategory.REGULATORY,
                url=href,
            )
        )
    return items


async def fetch() -> List[News]:
    """Fetch BEI announcements. Throttled to once per 5 minutes."""
    global _last_fetch_ts

    elapsed = time.monotonic() - _last_fetch_ts
    if elapsed < _MIN_INTERVAL_SEC:
        logger.info(
            "bei.throttled elapsed=%.1fs min=%ds — skipping fetch",
            elapsed, _MIN_INTERVAL_SEC,
        )
        return []

    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT, "Accept": "application/json,text/html"},
        ) as client:
            try:
                items = await _fetch_via_api(client)
                if items:
                    _last_fetch_ts = time.monotonic()
                    logger.info("bei.fetched via=api count=%d", len(items))
                    return items
                logger.info("bei.api_empty — trying HTML fallback")
            except Exception as api_exc:
                logger.warning("bei.api_failed error=%s — trying HTML fallback", api_exc)

            items = await _fetch_via_html(client)
            _last_fetch_ts = time.monotonic()
            logger.info("bei.fetched via=html count=%d", len(items))
            return items

    except Exception as exc:
        logger.warning("bei.fetch_failed error=%s", exc)
        return []
