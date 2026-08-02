"""
In-process pub/sub bus for live client streaming.

Producers (the news fast-poller, the commodity tracker, the scheduled refresh)
call `publish()`. Each connected WebSocket/SSE client holds one bounded queue;
`publish()` never blocks and never awaits a slow client — if a client's queue is
full its oldest event is dropped and a counter incremented. A stalled phone on a
bad connection therefore cannot apply backpressure to the scrapers or grow
memory without bound.

Single-process only. Running multiple workers means each process has its own bus
and a client connected to worker A will not see events produced on worker B —
that needs Redis pub/sub instead (see HANDOFF.md).
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Per-client buffer. Small on purpose: a client that falls this far behind is
# better served by refetching /news than by replaying a long backlog.
_QUEUE_MAXSIZE = 100

EVENT_NEWS = "news"
EVENT_COMMODITY = "commodity"
EVENT_HEARTBEAT = "heartbeat"


class Subscriber:
    """One connected client. Created via EventBus.subscribe()."""

    __slots__ = ("queue", "dropped", "name")

    def __init__(self, name: str) -> None:
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
        self.dropped = 0
        self.name = name


class EventBus:
    def __init__(self) -> None:
        self._subscribers: Set[Subscriber] = set()

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def subscribe(self, name: str = "client") -> Subscriber:
        sub = Subscriber(name)
        self._subscribers.add(sub)
        logger.info("events.subscribed name=%s total=%d", name, len(self._subscribers))
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        self._subscribers.discard(sub)
        logger.info(
            "events.unsubscribed name=%s dropped=%d total=%d",
            sub.name, sub.dropped, len(self._subscribers),
        )

    def publish(self, event_type: str, data: Any) -> int:
        """
        Fan out one event to every subscriber. Non-blocking and non-async so
        producers can call it from anywhere without awaiting. Returns the number
        of subscribers the event reached.
        """
        if not self._subscribers:
            return 0

        envelope = {
            "type": event_type,
            "ts": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }

        delivered = 0
        for sub in self._subscribers:
            try:
                sub.queue.put_nowait(envelope)
                delivered += 1
            except asyncio.QueueFull:
                # Drop the oldest event to make room — a live feed is more
                # useful fresh than complete.
                try:
                    sub.queue.get_nowait()
                    sub.queue.put_nowait(envelope)
                    delivered += 1
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass
                sub.dropped += 1
                if sub.dropped % 50 == 1:
                    logger.warning(
                        "events.slow_client name=%s dropped=%d", sub.name, sub.dropped
                    )
        return delivered

    def publish_news(self, items: List[Dict[str, Any]]) -> int:
        """Publish new news items. `items` are already JSON-safe dicts."""
        if not items:
            return 0
        return self.publish(EVENT_NEWS, items)

    def publish_commodity(self, quotes: List[Dict[str, Any]]) -> int:
        if not quotes:
            return 0
        return self.publish(EVENT_COMMODITY, quotes)


# Module-level singleton — producers import this directly.
bus = EventBus()


async def next_event(sub: Subscriber, timeout: Optional[float] = None) -> Optional[dict]:
    """
    Await the next event for a subscriber. Returns None on timeout so the
    caller can emit a keep-alive frame (proxies drop idle connections).
    """
    if timeout is None:
        return await sub.queue.get()
    try:
        return await asyncio.wait_for(sub.queue.get(), timeout=timeout)
    except asyncio.TimeoutError:
        return None
