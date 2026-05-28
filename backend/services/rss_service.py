"""
RSS feed fetcher for Indonesian financial news sources.
Tries sources in priority order and returns the first successful parse.
"""

import hashlib
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import List, Optional, Tuple

import feedparser
import httpx

from models.news import News, NewsCategory, NewsImportance, NewsSource
from services.ticker_service import detect_tickers

logger = logging.getLogger(__name__)

# ── Feed registry ─────────────────────────────────────────────────────────────
# (source_enum, feed_url)
#
# Indonesian news RSS URLs shift frequently and may be geo-restricted.
# Verify each URL is reachable from your deployment environment by opening
# it in a browser or running:
#   curl -A "KabarPasar/0.1" -L <url>
#
# To add / replace a feed: append a (NewsSource, url) tuple below.
FEEDS: List[Tuple[NewsSource, str]] = [
    # CNBC Indonesia market section — verify URL at cnbcindonesia.com
    (
        NewsSource.CNBC_INDONESIA,
        "https://www.cnbcindonesia.com/rss/market.rss",
    ),
    # Detik Finance — alternate paths to try if primary is 404:
    #   https://rss.detik.com/index.php/finance
    #   https://finance.detik.com/rss.xml
    (
        NewsSource.DETIK_FINANCE,
        "https://rss.detik.com/index.php/finance",
    ),
    # Bisnis Indonesia market feed
    (
        NewsSource.BISNIS_INDONESIA,
        "https://bisnis.com/rss/pasar-modal.rss",
    ),
    # Kontan — SSL cert issues on some networks; swap in if resolved
    # (NewsSource.KONTAN, "https://rss.kontan.co.id/action/rss/Kontan"),
]

# Seconds before giving up on a single feed fetch
_FEED_TIMEOUT = 10


def _stable_id(url: str, guid: str) -> str:
    """SHA-1 of (guid or url) → 12-char hex — stable across re-fetches."""
    raw = guid or url
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def _parse_date(entry: feedparser.FeedParserDict) -> str:
    """Return ISO-8601 UTC string from feed entry, fallback to now."""
    try:
        if hasattr(entry, "published"):
            dt = parsedate_to_datetime(entry.published)
            return dt.astimezone(timezone.utc).isoformat()
        if hasattr(entry, "updated"):
            dt = parsedate_to_datetime(entry.updated)
            return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        pass
    return datetime.now(timezone.utc).isoformat()


def _excerpt(entry: feedparser.FeedParserDict) -> str:
    """Best-effort one-paragraph excerpt from feed entry."""
    for attr in ("summary", "description", "content"):
        val = getattr(entry, attr, None)
        if val:
            if isinstance(val, list):
                val = val[0].get("value", "") if val else ""
            # Strip HTML tags roughly
            import re
            text = re.sub(r"<[^>]+>", " ", str(val))
            text = " ".join(text.split())
            return text[:400]
    return entry.get("title", "")


def _guess_category(title: str, excerpt: str) -> NewsCategory:
    """Heuristic category from keywords in title + excerpt."""
    text = (title + " " + excerpt).lower()

    if any(k in text for k in ["dividen", "rups", "rights issue", "buyback", "akuisisi",
                                 "merger", "spin-off", "stock split"]):
        return NewsCategory.CORPORATE_ACTION

    if any(k in text for k in ["laba", "pendapatan", "revenue", "earnings", "laporan keuangan",
                                 "kinerja", "q1", "q2", "q3", "q4", "semester"]):
        return NewsCategory.EARNINGS

    if any(k in text for k in ["ojk", "bei", "regulasi", "aturan", "peraturan",
                                 "izin", "sanksi", "suspensi"]):
        return NewsCategory.REGULATORY

    if any(k in text for k in ["bi rate", "inflasi", "suku bunga", "rupiah", "kurs",
                                 "gdp", "pdb", "fed", "the fed", "makro"]):
        return NewsCategory.MACRO

    return NewsCategory.MARKET_NEWS


def _fetch_feed(source: NewsSource, url: str) -> List[News]:
    """Fetch *url*, parse RSS/Atom entries, return list of News objects."""
    try:
        # feedparser can fetch directly but doesn't honour timeout well;
        # use httpx for the raw bytes then hand to feedparser.
        resp = httpx.get(url, timeout=_FEED_TIMEOUT, follow_redirects=True,
                         headers={"User-Agent": "KabarPasar/0.1 (RSS aggregator)"})
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
    except Exception as exc:
        logger.warning("Feed fetch failed for %s (%s): %s", source.value, url, exc)
        return []

    if feed.bozo and not feed.entries:
        logger.warning("Malformed feed from %s: %s", source.value, feed.bozo_exception)
        return []

    items: List[News] = []
    for entry in feed.entries:
        title   = entry.get("title", "").strip()
        link    = entry.get("link", "")
        guid    = entry.get("id", link)
        excerpt = _excerpt(entry)

        if not title:
            continue

        combined_text = title + " " + excerpt
        tickers       = detect_tickers(combined_text)
        category      = _guess_category(title, excerpt)

        items.append(
            News(
                id           = _stable_id(link, guid),
                title        = title,
                source       = source,
                published_at = _parse_date(entry),
                excerpt      = excerpt,
                ai_summary   = [],
                tickers      = tickers,
                importance   = NewsImportance.MEDIUM,
                category     = category,
                url          = link or None,
            )
        )

    logger.info("Fetched %d items from %s", len(items), source.value)
    return items


def fetch_all_news() -> List[News]:
    """
    Fetch from all configured feeds concurrently-ish (sequential for now),
    deduplicate by id, sort newest-first.
    """
    all_items: List[News] = []
    seen_ids: set = set()

    for source, url in FEEDS:
        items = _fetch_feed(source, url)
        for item in items:
            if item.id not in seen_ids:
                seen_ids.add(item.id)
                all_items.append(item)

    all_items.sort(key=lambda n: n.published_at, reverse=True)
    return all_items
