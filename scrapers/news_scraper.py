"""
Fast-lane news poller.

Polls a small set of high-value feeds far more often than the 5-minute
`scheduler.refresh_news_job` does, so breaking IDX news reaches connected
clients in seconds. Items are persisted through the same
`upsert_news_items` path, whose primary key is `stable_id()` — so this loop and
the scheduled refresh can both run without ever double-inserting: whichever
arrives first writes the row, the other sees zero new items.

Politeness (this is the part that keeps us un-banned):

* **Conditional GET.** Per-feed ETag / Last-Modified are cached and replayed as
  `If-None-Match` / `If-Modified-Since`. An unchanged feed answers `304` with an
  empty body — a few hundred bytes and no parsing. This is what makes frequent
  polling acceptable rather than abusive.
* **Publisher cache policy is the floor.** We read `Cache-Control: max-age` from
  the response and never re-poll that feed sooner. CNBC Indonesia sends
  `max-age=30`, i.e. "this cannot change for 30s" — polling faster would be
  guaranteed-identical requests.
* **429 / 503 are obeyed, not evaded.** `Retry-After` is honoured exactly; on
  repeated failures the feed backs off exponentially with jitter, up to
  `_MAX_BACKOFF`. There is no user-agent rotation here on purpose: rotating
  identity to slip past a rate limit is evading the publisher's stated limit,
  and it is also how an aggregator gets its whole IP range blocked. We send one
  honest, identifying UA and slow down when asked to.

Env:
  FAST_POLL_SECONDS   base interval per feed (default 30, floor 5)
  FAST_POLL_ENABLED   "0" to disable the loop entirely (default "1")
"""

import asyncio
import logging
import os
import random
import time
from email.utils import parsedate_to_datetime
from typing import Dict, List, Optional, Tuple

import httpx

from backend.models.news import News, NewsSource

from . import bloomberg_technoz, cnbc_indonesia, kontan
from .base import parse_feed_bytes

logger = logging.getLogger(__name__)

# One honest, identifying UA — see module docstring on why this is not rotated.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) KabarPasar/0.2 "
    "(+https://github.com/Nicholas-Martin007/kabar-pasar)"
)
_TIMEOUT = 12

_BASE_INTERVAL = max(5, int(os.getenv("FAST_POLL_SECONDS", "30")))
_ENABLED = os.getenv("FAST_POLL_ENABLED", "1") != "0"

_MAX_BACKOFF = 900.0        # 15 min ceiling for a persistently failing feed
_BACKOFF_FACTOR = 2.0
_JITTER = 0.25              # ±25% so feeds don't sync up into a thundering herd

# The fast lane deliberately covers only feeds that actually break news often.
# Everything else stays on the 5-minute scheduled refresh.
FEEDS: List[Tuple[NewsSource, str]] = [
    (NewsSource.KONTAN, kontan.FEED_URLS[0]),
    (NewsSource.CNBC_INDONESIA, cnbc_indonesia.FEED_URL),
    (NewsSource.BLOOMBERG_TECHNOZ, bloomberg_technoz.FEED_URL),
]


class FeedState:
    """Per-feed conditional-GET validators and backoff bookkeeping."""

    __slots__ = ("etag", "last_modified", "min_interval", "failures", "next_at")

    def __init__(self) -> None:
        self.etag: Optional[str] = None
        self.last_modified: Optional[str] = None
        # Raised to the publisher's Cache-Control max-age when they send one.
        self.min_interval: float = float(_BASE_INTERVAL)
        self.failures: int = 0
        self.next_at: float = 0.0

    def conditional_headers(self) -> Dict[str, str]:
        h: Dict[str, str] = {}
        if self.etag:
            h["If-None-Match"] = self.etag
        if self.last_modified:
            h["If-Modified-Since"] = self.last_modified
        return h

    def _jittered(self, seconds: float) -> float:
        return seconds * (1.0 + random.uniform(-_JITTER, _JITTER))

    def schedule_ok(self, now: float) -> None:
        self.failures = 0
        self.next_at = now + self._jittered(self.min_interval)

    def schedule_retry(self, now: float, retry_after: Optional[float] = None) -> float:
        """Exponential backoff, or an exact Retry-After when the server sent one."""
        self.failures += 1
        if retry_after is not None:
            delay = retry_after                      # obey the server exactly
        else:
            delay = min(
                self.min_interval * (_BACKOFF_FACTOR ** self.failures),
                _MAX_BACKOFF,
            )
            delay = self._jittered(delay)
        self.next_at = now + delay
        return delay


def _parse_retry_after(value: Optional[str]) -> Optional[float]:
    """Retry-After is either delta-seconds or an HTTP-date."""
    if not value:
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
        return max(0.0, when.timestamp() - time.time())
    except Exception:
        return None


def _parse_max_age(cache_control: Optional[str]) -> Optional[float]:
    if not cache_control:
        return None
    for part in cache_control.split(","):
        part = part.strip().lower()
        if part.startswith("max-age="):
            try:
                return float(part.split("=", 1)[1])
            except ValueError:
                return None
    return None


async def poll_feed(
    client: httpx.AsyncClient, source: NewsSource, url: str, state: FeedState
) -> List[News]:
    """
    One conditional GET. Returns parsed items, or [] for 304 / error.
    Updates `state` (validators, min_interval, backoff schedule).
    """
    now = time.monotonic()
    try:
        resp = await client.get(url, headers=state.conditional_headers())
    except Exception as exc:
        delay = state.schedule_retry(now)
        logger.warning(
            "fastpoll.error source=%s error=%s retry_in=%.0fs",
            source.value, exc, delay,
        )
        return []

    # Respect the publisher's own cache policy as our interval floor.
    max_age = _parse_max_age(resp.headers.get("Cache-Control"))
    if max_age is not None:
        state.min_interval = max(float(_BASE_INTERVAL), max_age)

    if resp.status_code == 304:
        state.schedule_ok(now)
        logger.debug("fastpoll.not_modified source=%s", source.value)
        return []

    if resp.status_code in (429, 503):
        retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
        delay = state.schedule_retry(now, retry_after)
        logger.warning(
            "fastpoll.rate_limited source=%s status=%d retry_after=%s backing_off=%.0fs",
            source.value, resp.status_code,
            "server" if retry_after is not None else "exponential", delay,
        )
        return []

    if resp.status_code >= 400:
        delay = state.schedule_retry(now)
        logger.warning(
            "fastpoll.http_error source=%s status=%d retry_in=%.0fs",
            source.value, resp.status_code, delay,
        )
        return []

    # Cache validators for the next request.
    state.etag = resp.headers.get("ETag") or state.etag
    state.last_modified = resp.headers.get("Last-Modified") or state.last_modified
    state.schedule_ok(now)

    items = await parse_feed_bytes(source, resp.content)
    logger.debug("fastpoll.fetched source=%s count=%d", source.value, len(items))
    return items


async def poll_once(
    client: httpx.AsyncClient, states: Dict[str, FeedState]
) -> List[News]:
    """Poll every feed whose backoff window has elapsed. Returns all parsed items."""
    now = time.monotonic()
    due = [(src, url) for src, url in FEEDS if states[url].next_at <= now]
    if not due:
        return []

    results = await asyncio.gather(
        *(poll_feed(client, src, url, states[url]) for src, url in due),
        return_exceptions=True,
    )

    items: List[News] = []
    for (src, _url), res in zip(due, results):
        if isinstance(res, BaseException):
            logger.warning("fastpoll.task_failed source=%s error=%s", src.value, res)
            continue
        items.extend(res)
    return items


async def persist_and_broadcast(items: List[News]) -> int:
    """
    Persist via the shared dedup path and push genuinely-new items to clients.
    Imported lazily so this module stays importable without the DB configured
    (keeps it unit-testable).
    """
    if not items:
        return 0

    from backend.db.repository import upsert_news_items
    from backend.db.session import get_session
    from backend.services.events import bus

    async with get_session() as session:
        new_items = await upsert_news_items(session, items)

    if new_items:
        bus.publish_news([n.model_dump(by_alias=True, mode="json") for n in new_items])
        logger.info("fastpoll.new count=%d", len(new_items))
    return len(new_items)


async def poll_loop() -> None:
    """Run forever. Cancelled on app shutdown."""
    if not _ENABLED:
        logger.info("fastpoll.disabled FAST_POLL_ENABLED=0")
        return

    states: Dict[str, FeedState] = {url: FeedState() for _src, url in FEEDS}
    logger.info(
        "fastpoll.started feeds=%d base_interval=%ds", len(FEEDS), _BASE_INTERVAL
    )

    async with httpx.AsyncClient(
        timeout=_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": _USER_AGENT, "Accept-Encoding": "gzip, deflate"},
    ) as client:
        while True:
            try:
                items = await poll_once(client, states)
                await persist_and_broadcast(items)
            except asyncio.CancelledError:
                logger.info("fastpoll.stopped")
                raise
            except Exception as exc:
                logger.exception("fastpoll.cycle_failed error=%s", exc)

            # Wake when the earliest feed is next due (never busier than 1s).
            now = time.monotonic()
            sleep_for = min((s.next_at for s in states.values()), default=now + 1) - now
            await asyncio.sleep(max(1.0, sleep_for))
