"""
Shared utilities for RSS-based sources.

Each source module wraps `fetch_rss(source, url)` with its own NewsSource enum
and feed URL. Heavy lifting (HTTP fetch, parsing, ticker detection, category
heuristic, stable id) lives here so per-source files stay 5-10 lines.
"""

import asyncio
import hashlib
import logging
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import List

import feedparser
import httpx

from backend.models.news import News, NewsCategory, NewsImportance, NewsSource
from backend.services.ticker_service import detect_tickers

logger = logging.getLogger(__name__)

_FEED_TIMEOUT = 12
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) KabarPasar/0.1"


def stable_id(url: str, guid: str = "") -> str:
    """SHA-1(guid or url) → 12-char hex. Stable across re-fetches."""
    return hashlib.sha1((guid or url).encode()).hexdigest()[:12]


def parse_date(entry: feedparser.FeedParserDict) -> str:
    """ISO-8601 UTC string from feed entry. Fallback to now()."""
    for attr in ("published", "updated"):
        val = getattr(entry, attr, None)
        if not val:
            continue
        try:
            return parsedate_to_datetime(val).astimezone(timezone.utc).isoformat()
        except Exception:
            continue
    return datetime.now(timezone.utc).isoformat()


def excerpt(entry: feedparser.FeedParserDict) -> str:
    """One-paragraph excerpt, HTML stripped, max 400 chars."""
    for attr in ("summary", "description", "content"):
        val = getattr(entry, attr, None)
        if not val:
            continue
        if isinstance(val, list):
            val = val[0].get("value", "") if val else ""
        text = re.sub(r"<[^>]+>", " ", str(val))
        text = " ".join(text.split())
        if text:
            return text[:400]
    return entry.get("title", "")


def guess_category(title: str, body: str) -> NewsCategory:
    text = (title + " " + body).lower()
    if any(k in text for k in (
        "dividen", "rups", "rights issue", "buyback", "akuisisi",
        "merger", "spin-off", "stock split",
    )):
        return NewsCategory.CORPORATE_ACTION
    if any(k in text for k in (
        "laba", "pendapatan", "revenue", "earnings", "laporan keuangan",
        "kinerja", "q1", "q2", "q3", "q4", "semester",
    )):
        return NewsCategory.EARNINGS
    if any(k in text for k in (
        "ojk", "bei", "regulasi", "aturan", "peraturan", "izin", "sanksi", "suspensi",
    )):
        return NewsCategory.REGULATORY
    if any(k in text for k in (
        "bi rate", "inflasi", "suku bunga", "rupiah", "kurs",
        "gdp", "pdb", "fed", "the fed", "makro",
    )):
        return NewsCategory.MACRO
    return NewsCategory.MARKET_NEWS


# Keyword heuristics for importance (free; no AI). Conservative on HIGH.
_HIGH_KEYWORDS = (
    # corporate actions
    "dividen", "rights issue", "right issue", "buyback", "akuisisi", "merger",
    "stock split", "tender offer", "private placement", "ipo", "go public",
    "rups", "caplok", "ambil alih", "divestasi", "akuisisteen",
    # distress / regulatory
    "suspensi", "delisting", "pailit", "gagal bayar", "pkpu", "sanksi ojk",
    "dibekukan", "bangkrut",
    # market-moving macro / geopolitics
    "bi rate", "suku bunga acuan", "the fed", "rate cut", "rate hike",
    "tarif impor", "tariff", "perang", "invasi", "embargo", "resesi",
)
_LOW_KEYWORDS = (
    "rekomendasi saham", "simak", "ini dia", "tips", "cara ", "zodiak",
    "ramalan", "wisata", "resep", "lifestyle", "sepak bola", "drama korea",
    "harga emas antam hari ini", "kurs rupiah hari ini",
)


def score_importance(title: str, body: str = "") -> NewsImportance:
    text = (title + " " + body).lower()
    if any(k in text for k in _HIGH_KEYWORDS):
        return NewsImportance.HIGH
    if any(k in text for k in _LOW_KEYWORDS):
        return NewsImportance.LOW
    return NewsImportance.MEDIUM


async def fetch_rss(source: NewsSource, url: str) -> List[News]:
    """Fetch one RSS feed and return parsed News items."""
    try:
        async with httpx.AsyncClient(
            timeout=_FEED_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            # feedparser.parse is CPU-bound; run in thread to keep loop free
            feed = await asyncio.to_thread(feedparser.parse, resp.content)
    except Exception as exc:
        logger.warning(
            "rss.fetch_failed source=%s url=%s error=%s", source.value, url, exc
        )
        return []

    if feed.bozo and not feed.entries:
        logger.warning(
            "rss.malformed source=%s error=%s", source.value, feed.bozo_exception
        )
        return []

    items: List[News] = []
    for entry in feed.entries:
        title = entry.get("title", "").strip()
        if not title:
            continue
        link = entry.get("link", "")
        guid = entry.get("id", link)
        body = excerpt(entry)
        items.append(
            News(
                id=stable_id(link, guid),
                title=title,
                source=source,
                published_at=parse_date(entry),
                excerpt=body,
                ai_summary=[],
                tickers=detect_tickers(title + " " + body),
                importance=score_importance(title, body),
                category=guess_category(title, body),
                url=link or None,
            )
        )

    logger.info("rss.fetched source=%s count=%d", source.value, len(items))
    return items
