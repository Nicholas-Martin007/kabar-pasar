"""
Background worker queue.

Keeps slow, bursty work off the request/stream path. Chart rendering
(yfinance download + matplotlib) and screener sweeps take seconds and hold a
global render lock; running them inline stalls the SSE/WebSocket broadcast and
every other request behind them.

    from backend.tasks import submit
    await submit(send_pick_chart, "BBCA.JK", chat_id, name="pick:BBCA.JK")

Design notes:

* **Bounded queue, drop-newest.** An unbounded queue turns a scraper bug into
  an out-of-memory crash. When full we reject the new job and say so, rather
  than silently growing or blocking the caller (blocking is what this module
  exists to avoid).
* **Coalescing by key.** Enqueueing the same key twice while it's still pending
  is a no-op — ten alerts for the same ticker in one refresh cycle should
  render one chart, not ten.
* **Failures are contained.** A raising job is logged and the worker keeps
  going; one bad ticker must not kill the pool.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

_MAX_QUEUE = 200
_DEFAULT_WORKERS = 2


@dataclass
class _Job:
    fn: Callable[..., Awaitable[Any]]
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)
    name: str = "job"
    key: Optional[str] = None
    queued_at: float = field(default_factory=time.monotonic)


class WorkerPool:
    def __init__(self, workers: int = _DEFAULT_WORKERS, maxsize: int = _MAX_QUEUE) -> None:
        # The queue is NOT built here. On Python 3.9 an asyncio.Queue binds to
        # whatever loop is current at construction, and this module creates a
        # singleton at import time — long before uvicorn (or asyncio.run in a
        # test) starts the real loop. A queue bound to the wrong loop still
        # accepts put_nowait, but workers awaiting get() on the running loop
        # never wake, so jobs sit at submitted>0 / done==0 forever. Deferring
        # construction to start() binds it to the loop that actually runs it.
        self._queue: Optional[asyncio.Queue] = None
        self._workers: List[asyncio.Task] = []
        self._n = workers
        self._maxsize = maxsize
        self._pending_keys: Set[str] = set()
        self._stats = {"submitted": 0, "done": 0, "failed": 0, "rejected": 0, "coalesced": 0}

    # ── lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._workers:
            return
        self._queue = asyncio.Queue(maxsize=self._maxsize)
        for i in range(self._n):
            self._workers.append(asyncio.create_task(self._run(i), name=f"worker-{i}"))
        logger.info("tasks.pool_started workers=%d maxsize=%d", self._n, self._maxsize)

    async def stop(self) -> None:
        for t in self._workers:
            t.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        self._queue = None
        self._pending_keys.clear()
        logger.info("tasks.pool_stopped stats=%s", self._stats)

    # ── submission ───────────────────────────────────────────────────────────

    async def submit(
        self,
        fn: Callable[..., Awaitable[Any]],
        *args: Any,
        name: str = "job",
        key: Optional[str] = None,
        **kwargs: Any,
    ) -> bool:
        """
        Enqueue work. Returns False if rejected (queue full) or coalesced away.

        Never blocks: the whole point is that callers on the hot path — a
        scraper cycle, an SSE broadcast — hand work off and move on.
        """
        if self._queue is None:
            # Submitting before start() would otherwise fail with an opaque
            # AttributeError deep in the caller.
            logger.warning("tasks.not_started name=%s — call pool.start() first", name)
            return False

        if key is not None and key in self._pending_keys:
            self._stats["coalesced"] += 1
            logger.debug("tasks.coalesced key=%s", key)
            return False

        job = _Job(fn=fn, args=args, kwargs=kwargs, name=name, key=key)
        try:
            self._queue.put_nowait(job)
        except asyncio.QueueFull:
            self._stats["rejected"] += 1
            logger.warning(
                "tasks.rejected name=%s depth=%d — queue full, dropping",
                name, self._queue.qsize(),
            )
            return False

        if key is not None:
            self._pending_keys.add(key)
        self._stats["submitted"] += 1
        return True

    # ── worker loop ──────────────────────────────────────────────────────────

    async def _run(self, worker_id: int) -> None:
        queue = self._queue
        assert queue is not None, "start() builds the queue before spawning workers"
        while True:
            try:
                job = await queue.get()
            except asyncio.CancelledError:
                raise
            waited = time.monotonic() - job.queued_at
            started = time.monotonic()
            try:
                await job.fn(*job.args, **job.kwargs)
                self._stats["done"] += 1
                logger.info(
                    "tasks.done name=%s worker=%d waited=%.2fs ran=%.2fs",
                    job.name, worker_id, waited, time.monotonic() - started,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Contained on purpose: one bad ticker must not take the pool down.
                self._stats["failed"] += 1
                logger.warning("tasks.failed name=%s error=%s", job.name, exc)
            finally:
                if job.key is not None:
                    self._pending_keys.discard(job.key)
                queue.task_done()

    # ── introspection ────────────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        return {
            **self._stats,
            "depth": self._queue.qsize() if self._queue is not None else 0,
            "workers": len(self._workers),
            "pending_keys": len(self._pending_keys),
        }


# Module-level pool — started/stopped from the FastAPI lifespan.
pool = WorkerPool()


async def submit(
    fn: Callable[..., Awaitable[Any]],
    *args: Any,
    name: str = "job",
    key: Optional[str] = None,
    **kwargs: Any,
) -> bool:
    """Convenience wrapper around the module pool."""
    return await pool.submit(fn, *args, name=name, key=key, **kwargs)
