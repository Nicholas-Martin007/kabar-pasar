"""
Telegram bot for free watchlist news alerts.

Two halves:
  • a long-poll loop that handles user commands (/start /watch /unwatch /list /stop)
  • dispatch_alerts(), called by the refresh job, which pushes new matching news
    to each subscriber's chat.

Self-contained watchlist (managed via bot commands) so it doesn't depend on the
app's local watchlist. Disabled gracefully when TELEGRAM_BOT_TOKEN is unset.
"""

import asyncio
import html
import logging
import os
import secrets
import time
from typing import Dict, List, Optional, Tuple

import httpx

from db import repository as repo
from db.session import get_session
from models.news import News

logger = logging.getLogger(__name__)

_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
_API = "https://api.telegram.org/bot{token}/{method}"
_ALERTS_PER_CYCLE = 5  # cap messages per subscriber per refresh to avoid spam

# Ephemeral link codes for connecting the app's in-app watchlist to a chat.
_LINK_TTL_SEC = 600  # 10 minutes
_link_codes: Dict[str, Tuple[str, float]] = {}  # code -> (chat_id, expiry)

HELP = (
    "<b>Kabar Pasar — Notifikasi Saham</b>\n\n"
    "Perintah:\n"
    "/watch BBCA — pantau saham\n"
    "/unwatch BBCA — berhenti pantau\n"
    "/news — berita terbaru watchlist-mu\n"
    "/list — lihat watchlist\n"
    "/link — hubungkan watchlist dari app\n"
    "/stop — berhenti semua notifikasi\n\n"
    "Kamu akan menerima berita terbaru untuk saham di watchlist-mu, dari "
    "Bloomberg Technoz, Kontan, CNBC Indonesia, Detik, Bisnis & BEI."
)


def new_link_code(chat_id: str) -> str:
    """Generate a 6-digit code that the app exchanges to link this chat."""
    code = f"{secrets.randbelow(1_000_000):06d}"
    _link_codes[code] = (chat_id, time.time() + _LINK_TTL_SEC)
    return code


def consume_link_code(code: str) -> Optional[str]:
    """Return the chat_id for a valid, unexpired code (single use)."""
    entry = _link_codes.pop(code.strip(), None)
    if not entry:
        return None
    chat_id, expiry = entry
    return chat_id if time.time() <= expiry else None


def is_enabled() -> bool:
    return bool(_TOKEN)


async def _post(method: str, payload: dict, timeout: float = 15) -> Optional[dict]:
    url = _API.format(token=_TOKEN, method=method)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        logger.warning("telegram.post_failed method=%s error=%s", method, exc)
        return None


async def send_message(chat_id: str, text: str) -> None:
    if not _TOKEN:
        return
    await _post(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
    )


# ── Alert dispatch (called from the refresh job) ──────────────────────────────

def _format_alert(item: News) -> str:
    tickers = ", ".join(item.tickers)
    lines = [f"📈 <b>{html.escape(tickers)}</b>", html.escape(item.title)]
    if item.impact:
        lines.append(f"💡 {html.escape(item.impact)}")
    lines.append(f"<i>{html.escape(item.source.value)}</i>")
    if item.url:
        lines.append(item.url)
    return "\n".join(lines)


async def dispatch_alerts(new_items: List[News]) -> int:
    """Push newly-ingested, ticker-tagged news to matching subscribers."""
    if not _TOKEN:
        return 0
    items = [n for n in new_items if n.tickers]
    if not items:
        return 0

    async with get_session() as session:
        subscribers = await repo.list_subscribers(session)

    sent = 0
    for sub in subscribers:
        watch = set(sub["tickers"])
        if not watch:
            continue
        matched = [n for n in items if watch.intersection(n.tickers)]
        for item in matched[:_ALERTS_PER_CYCLE]:
            await send_message(sub["chat_id"], _format_alert(item))
            sent += 1
    if sent:
        logger.info("telegram.alerts_sent count=%d", sent)
    return sent


# ── Command handling + long-poll loop ─────────────────────────────────────────

async def _handle_command(chat_id: str, text: str) -> None:
    parts = text.strip().split()
    cmd = parts[0].lower().lstrip("/").split("@")[0]
    arg = parts[1].upper() if len(parts) > 1 else ""

    async with get_session() as session:
        if cmd in ("start", "help"):
            await repo.ensure_subscriber(session, chat_id)
            reply = HELP
        elif cmd == "watch" and arg:
            tickers = await repo.add_subscriber_ticker(session, chat_id, arg)
            reply = f"✅ {arg} ditambahkan.\nWatchlist: {', '.join(tickers) or '—'}"
        elif cmd == "unwatch" and arg:
            tickers = await repo.remove_subscriber_ticker(session, chat_id, arg)
            reply = f"❎ {arg} dihapus.\nWatchlist: {', '.join(tickers) or '—'}"
        elif cmd == "list":
            tickers = await repo.get_subscriber_tickers(session, chat_id)
            reply = f"📋 Watchlist: {', '.join(tickers) or 'kosong'}"
        elif cmd == "news":
            tickers = await repo.get_subscriber_tickers(session, chat_id)
            if not tickers:
                reply = "Watchlist kosong. Tambah dulu, contoh: /watch BBCA"
            else:
                items = await repo.latest_news_for_tickers(session, tickers, limit=5)
                if not items:
                    reply = f"Belum ada berita terbaru untuk: {', '.join(tickers)}"
                else:
                    parts = ["📰 <b>Berita Watchlist</b>"]
                    for it in items:
                        tix = ", ".join(it["tickers"])
                        block = (
                            f"\n• <b>{html.escape(tix)}</b> — "
                            f"{html.escape(it['title'])}\n  <i>{html.escape(it['source'])}</i>"
                        )
                        if it["url"]:
                            block += f"\n  {it['url']}"
                        parts.append(block)
                    reply = "\n".join(parts)
        elif cmd == "link":
            code = new_link_code(chat_id)
            reply = (
                f"🔗 Kode tautan: <b>{code}</b>\n"
                "Masukkan di app Kabar Pasar (Profil → Hubungkan Telegram) "
                "dalam 10 menit. Watchlist app-mu akan otomatis tersinkron."
            )
        elif cmd == "stop":
            await repo.remove_subscriber(session, chat_id)
            reply = "🛑 Berhenti. Kamu tidak akan menerima notifikasi lagi."
        else:
            reply = HELP

    await send_message(chat_id, reply)


async def poll_updates_loop() -> None:
    """Long-poll getUpdates and route commands. Runs until cancelled."""
    if not _TOKEN:
        logger.info("telegram.disabled (set TELEGRAM_BOT_TOKEN to enable)")
        return

    offset = 0
    logger.info("telegram.poller.started")
    while True:
        try:
            data = await _post(
                "getUpdates", {"offset": offset, "timeout": 30}, timeout=40
            )
            for upd in (data or {}).get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message") or upd.get("edited_message")
                if not msg:
                    continue
                text = (msg.get("text") or "").strip()
                chat = msg.get("chat") or {}
                chat_id = str(chat.get("id", ""))
                if chat_id and text.startswith("/"):
                    await _handle_command(chat_id, text)
        except asyncio.CancelledError:
            logger.info("telegram.poller.stopped")
            break
        except Exception as exc:
            logger.warning("telegram.poll_error error=%s", exc)
            await asyncio.sleep(5)
