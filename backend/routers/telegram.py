"""Telegram linking API — connect the app's in-app watchlist to a chat."""

import logging
import secrets
from typing import List

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from db import repository as repo
from db.session import get_session
from services.telegram_service import consume_link_code, is_enabled

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/telegram", tags=["telegram"])


class LinkRequest(BaseModel):
    code: str
    tickers: List[str] = Field(default_factory=list)


class SyncRequest(BaseModel):
    linkToken: str
    tickers: List[str] = Field(default_factory=list)


@router.get("/enabled")
async def telegram_enabled() -> dict:
    """Whether the backend has a bot token configured."""
    return {"enabled": is_enabled()}


@router.post("/link")
async def telegram_link(body: LinkRequest) -> dict:
    """Exchange a /link code for a persistent token; seed the chat's watchlist."""
    chat_id = consume_link_code(body.code)
    if not chat_id:
        raise HTTPException(status_code=400, detail="Kode tidak valid atau kedaluwarsa")
    token = secrets.token_urlsafe(16)
    async with get_session() as session:
        await repo.link_subscriber(session, chat_id, token, body.tickers)
    return {"ok": True, "linkToken": token, "tickerCount": len(body.tickers)}


@router.post("/sync")
async def telegram_sync(body: SyncRequest) -> dict:
    """Push the latest in-app watchlist to the linked chat."""
    async with get_session() as session:
        ok = await repo.sync_subscriber_by_token(session, body.linkToken, body.tickers)
    if not ok:
        raise HTTPException(status_code=404, detail="Tautan tidak ditemukan")
    return {"ok": True, "tickerCount": len(body.tickers)}


@router.get("/status")
async def telegram_status(
    linkToken: str = Query(..., description="The app's stored link token"),
) -> dict:
    async with get_session() as session:
        sub = await repo.get_subscriber_by_token(session, linkToken)
    return {"linked": sub is not None, "tickers": sub["tickers"] if sub else []}
