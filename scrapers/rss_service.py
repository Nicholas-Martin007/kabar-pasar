"""
News aggregator: fan-out to every registered source in parallel, then dedupe.

Adding a new source:
  1. Drop a module in `scrapers/` exposing `async fetch() -> List[News]`.
  2. Import + append it to SOURCES below.
"""

import asyncio
import logging
import re
from typing import Callable, Coroutine, List

from backend.models.news import News
from . import (
    antara,
    bei,
    bisnis_indonesia,
    bloomberg_technoz,
    cnbc_global,
    cnbc_indonesia,
    detik,
    investor_id,
    katadata,
    kontan,
    liputan6,
    yahoo_finance,
)

logger = logging.getLogger(__name__)

# Tuple of (name, fetch_callable). Order = priority when titles collide on dedupe.
SOURCES: List[tuple[str, Callable[[], Coroutine]]] = [
    ("bei",              bei.fetch),
    ("cnbc_indonesia",   cnbc_indonesia.fetch),
    ("detik",            detik.fetch),
    ("kontan",           kontan.fetch),
    ("bisnis_indonesia", bisnis_indonesia.fetch),
    ("bloomberg_technoz", bloomberg_technoz.fetch),
    ("yahoo_finance",    yahoo_finance.fetch),
    ("cnbc_global",      cnbc_global.fetch),
    ("katadata",         katadata.fetch),
    ("antara",           antara.fetch),
    ("liputan6",         liputan6.fetch),
    ("investor_id",      investor_id.fetch),
]


def _normalize_title(title: str) -> str:
    """Lowercase, strip non-alphanumerics, collapse whitespace.

    Used for cross-source duplicate detection — two articles with the same
    normalized title are treated as duplicates regardless of URL.
    """
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", title.lower()).split())


def _dedupe(items: List[News]) -> List[News]:
    """Keep first occurrence by stable id OR normalized title."""
    seen_ids: set[str] = set()
    seen_titles: set[str] = set()
    out: List[News] = []
    for item in items:
        norm = _normalize_title(item.title)
        if item.id in seen_ids or norm in seen_titles:
            continue
        seen_ids.add(item.id)
        seen_titles.add(norm)
        out.append(item)
    return out


async def fetch_all_news() -> List[News]:
    """
    Fetch every source concurrently. Per-source failures are isolated:
    `return_exceptions=True` keeps the aggregator alive when one feed dies.
    """
    results = await asyncio.gather(
        *(fn() for _, fn in SOURCES), return_exceptions=True
    )

    all_items: List[News] = []
    for (name, _), result in zip(SOURCES, results):
        if isinstance(result, Exception):
            logger.warning("aggregator.source_failed source=%s error=%s", name, result)
            continue
        all_items.extend(result)

    before = len(all_items)
    deduped = _dedupe(all_items)
    deduped.sort(key=lambda n: n.published_at, reverse=True)

    logger.info(
        "aggregator.complete sources=%d raw=%d deduped=%d",
        len(SOURCES), before, len(deduped),
    )
    return deduped
