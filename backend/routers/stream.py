"""
Live event streaming: WebSocket + SSE.

Both endpoints carry the same envelopes off the same bus:

    {"type": "news",      "ts": "...", "data": [ <News>, ... ]}
    {"type": "commodity", "ts": "...", "data": [ <quote>, ... ]}
    {"type": "heartbeat", "ts": "...", "data": null}

WebSocket is the primary transport for the React Native app. SSE exists because
it survives corporate proxies that break WS upgrades and needs no client
library — handy for debugging with plain `curl`.

Heartbeats every `_HEARTBEAT_SEC` keep idle connections from being reaped by
intermediaries and let clients detect a dead link without waiting for news.
"""

import asyncio
import json
import logging
from typing import AsyncIterator

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from backend.db.repository import latest_commodity_prices
from backend.db.session import get_session
from backend.services.events import EVENT_COMMODITY, EVENT_HEARTBEAT, bus, next_event

logger = logging.getLogger(__name__)

router = APIRouter(tags=["stream"])

_HEARTBEAT_SEC = 25.0


async def _initial_snapshot() -> dict:
    """
    Current commodity levels, sent once on connect.

    Without this a client sees nothing until the next tick — up to a full poll
    interval of blank UI. News is deliberately not included: clients already
    load it from GET /news, and replaying it here would duplicate their list.
    """
    try:
        async with get_session() as session:
            quotes = await latest_commodity_prices(session)
    except Exception as exc:
        logger.warning("stream.snapshot_failed error=%s", exc)
        return {}
    if not quotes:
        return {}
    return {"type": EVENT_COMMODITY, "ts": None, "data": quotes}


async def _drain_incoming(websocket: WebSocket) -> None:
    """
    Consume (and discard) client frames purely to observe disconnects.

    This stream is server->client only, but without an active receive the ASGI
    layer has nothing to read the close frame from, so a vanished client is not
    noticed until the next *send* fails — up to a full heartbeat later. On a
    mobile network that churns connections, subscribers would pile up in the
    bus for ~25s each. Racing a receive against the send loop makes teardown
    immediate.
    """
    while True:
        await websocket.receive_text()


@router.websocket("/stream/ws")
async def stream_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    client = f"{websocket.client.host}:{websocket.client.port}" if websocket.client else "ws"
    sub = bus.subscribe(client)

    async def send_loop() -> None:
        snapshot = await _initial_snapshot()
        if snapshot:
            await websocket.send_text(json.dumps(snapshot))
        while True:
            event = await next_event(sub, timeout=_HEARTBEAT_SEC)
            if event is None:
                await websocket.send_text(
                    json.dumps({"type": EVENT_HEARTBEAT, "ts": None, "data": None})
                )
                continue
            await websocket.send_text(json.dumps(event))

    sender = asyncio.create_task(send_loop())
    receiver = asyncio.create_task(_drain_incoming(websocket))
    try:
        # Whichever finishes first ends the connection: the receiver on client
        # disconnect, the sender on a write error.
        done, pending = await asyncio.wait(
            {sender, receiver}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if exc and not isinstance(exc, (WebSocketDisconnect, asyncio.CancelledError)):
                logger.warning("stream.ws_error client=%s error=%s", client, exc)
    except asyncio.CancelledError:
        sender.cancel()
        receiver.cancel()
        raise
    finally:
        for task in (sender, receiver):
            task.cancel()
        await asyncio.gather(sender, receiver, return_exceptions=True)
        bus.unsubscribe(sub)
        logger.info("stream.ws_closed client=%s", client)


async def _sse_events(request: Request, client: str) -> AsyncIterator[str]:
    sub = bus.subscribe(client)
    try:
        snapshot = await _initial_snapshot()
        if snapshot:
            yield f"event: {snapshot['type']}\ndata: {json.dumps(snapshot)}\n\n"

        while True:
            # Client hung up — stop before doing any more work.
            if await request.is_disconnected():
                break

            event = await next_event(sub, timeout=_HEARTBEAT_SEC)
            if event is None:
                yield ": keep-alive\n\n"      # SSE comment frame
                continue
            yield f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"

    except asyncio.CancelledError:
        raise
    finally:
        bus.unsubscribe(sub)


@router.get("/stream/sse")
async def stream_sse(request: Request) -> StreamingResponse:
    client = f"{request.client.host}" if request.client else "sse"
    return StreamingResponse(
        _sse_events(request, client),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",   # nginx: don't buffer the stream
        },
    )


@router.get("/stream/status")
async def stream_status() -> dict:
    """Connected-client count — for debugging that the bus is actually wired."""
    return {"subscribers": bus.subscriber_count}
