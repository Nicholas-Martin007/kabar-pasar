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

_API = "https://api.telegram.org/bot{token}/{method}"


def _token() -> str:
    """Read the token lazily so it picks up .env loaded after import."""
    return os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
_ALERTS_PER_CYCLE = 5  # cap messages per subscriber per refresh to avoid spam

# Ephemeral link codes for connecting the app's in-app watchlist to a chat.
_LINK_TTL_SEC = 600  # 10 minutes
_link_codes: Dict[str, Tuple[str, float]] = {}  # code -> (chat_id, expiry)

HELP = (
    "<b>Kabar Pasar — Notifikasi Saham</b>\n\n"
    "Secara default kamu menerima <b>SEMUA berita</b>. Atur sesukamu:\n\n"
    "<b>Saring</b>\n"
    "/mute emas — bisukan topik/sumber (cth: gold, bola, bloomberg)\n"
    "/unmute emas — aktifkan lagi\n"
    "/all off — berhenti terima semua · /all on — terima semua lagi\n\n"
    "<b>Mode pilihan</b> (saat /all off)\n"
    "/watch BBCA — hanya saham tertentu\n"
    "/follow emas — hanya topik tertentu\n"
    "/unwatch · /unfollow — kebalikannya\n\n"
    "<b>Lainnya</b>\n"
    "/news 15 — tampilkan N berita terbaru (default 10)\n"
    "/list — lihat pengaturanmu\n"
    "/link — hubungkan watchlist dari app\n"
    "/stop — berhenti total\n\n"
    "Sumber: Bloomberg Technoz, Kontan, CNBC Indonesia, Detik, Bisnis &amp; BEI."
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
    return bool(_token())


async def _post(method: str, payload: dict, timeout: float = 15) -> Optional[dict]:
    url = _API.format(token=_token(), method=method)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        logger.warning("telegram.post_failed method=%s error=%s", method, exc)
        return None


async def send_message(chat_id: str, text: str) -> None:
    if not _token():
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
    head = ", ".join(item.tickers) if item.tickers else item.source.value
    icon = "📈" if item.tickers else "📰"
    lines = [f"{icon} <b>{html.escape(head)}</b>", html.escape(item.title)]
    if item.impact:
        lines.append(f"💡 {html.escape(item.impact)}")
    if item.tickers:
        lines.append(f"<i>{html.escape(item.source.value)}</i>")
    if item.url:
        lines.append(item.url)
    return "\n".join(lines)


def _matches(sub: dict, item: News) -> bool:
    """
    Firehose (all_news): everything EXCEPT muted topics/sources.
    Selective: watchlist tickers OR followed keywords.
    """
    hay = f"{item.title} {item.excerpt} {item.source.value}".lower()
    if sub.get("all_news"):
        mutes = sub.get("mute") or []
        return not any(m in hay for m in mutes)
    if set(sub.get("tickers") or []).intersection(item.tickers):
        return True
    keywords = sub.get("keywords") or []
    return any(kw in hay for kw in keywords) if keywords else False


async def dispatch_alerts(new_items: List[News]) -> int:
    """Push newly-ingested news to subscribers by watchlist / topic / firehose."""
    if not _token() or not new_items:
        return 0

    async with get_session() as session:
        subscribers = await repo.list_subscribers(session)

    sent = 0
    for sub in subscribers:
        matched = [n for n in new_items if _matches(sub, n)]
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
        if cmd == "start":
            await repo.ensure_subscriber(session, chat_id)
            reply = (
                "👋 <b>Selamat datang di Kabar Pasar!</b>\n\n"
                "Mulai sekarang kamu menerima <b>SEMUA berita</b> pasar "
                "(Bloomberg Technoz, Kontan, CNBC, Detik, Bisnis, BEI).\n\n"
                "• Terlalu ramai? /mute &lt;topik&gt; (cth: /mute bola)\n"
                "• Mau berhenti total: /all off\n"
                "• Lihat semua perintah: /help"
            )
        elif cmd == "help":
            await repo.ensure_subscriber(session, chat_id)
            reply = HELP
        elif cmd == "watch" and arg:
            tickers = await repo.add_subscriber_ticker(session, chat_id, arg)
            reply = f"✅ {arg} ditambahkan.\nWatchlist: {', '.join(tickers) or '—'}"
        elif cmd == "unwatch" and arg:
            tickers = await repo.remove_subscriber_ticker(session, chat_id, arg)
            reply = f"❎ {arg} dihapus.\nWatchlist: {', '.join(tickers) or '—'}"
        elif cmd == "follow" and arg:
            keywords = await repo.add_subscriber_keyword(session, chat_id, arg)
            reply = f"✅ Mengikuti topik «{arg.lower()}».\nTopik: {', '.join(keywords) or '—'}"
        elif cmd == "unfollow" and arg:
            keywords = await repo.remove_subscriber_keyword(session, chat_id, arg)
            reply = f"❎ Berhenti «{arg.lower()}».\nTopik: {', '.join(keywords) or '—'}"
        elif cmd == "mute" and arg:
            muted = await repo.add_subscriber_mute(session, chat_id, arg)
            reply = f"🔇 Membisukan «{arg.lower()}».\nDibisukan: {', '.join(muted) or '—'}"
        elif cmd == "unmute" and arg:
            muted = await repo.remove_subscriber_mute(session, chat_id, arg)
            reply = f"🔈 Aktif lagi «{arg.lower()}».\nDibisukan: {', '.join(muted) or '—'}"
        elif cmd == "all":
            on = arg.lower() in ("on", "1", "ya", "true", "")  # bare /all = on
            await repo.set_subscriber_all_news(session, chat_id, on)
            reply = (
                "📡 Semua berita: AKTIF. Kamu menerima setiap berita (kecuali yang dibisukan)."
                if on
                else "📴 Semua berita: NONAKTIF. Hanya /watch & /follow yang dikirim."
            )
        elif cmd == "list":
            sub = await repo.get_subscriber(session, chat_id)
            if not sub:
                reply = "Belum mulai. Kirim /start untuk menerima semua berita."
            else:
                reply = (
                    f"📋 <b>Pengaturanmu</b>\n"
                    f"Semua berita: {'AKTIF' if sub['all_news'] else 'nonaktif'}\n"
                    f"Dibisukan: {', '.join(sub['mute']) or '—'}\n"
                    f"Saham (mode pilihan): {', '.join(sub['tickers']) or '—'}\n"
                    f"Topik (mode pilihan): {', '.join(sub['keywords']) or '—'}"
                )
        elif cmd == "news":
            n = int(arg) if arg.isdigit() else 10
            n = max(1, min(20, n))  # clamp 1–20
            sub = await repo.get_subscriber(session, chat_id)
            tickers = sub["tickers"] if sub else []
            selective = bool(sub) and not sub["all_news"] and bool(tickers)
            if selective:
                items = await repo.latest_news_for_tickers(session, tickers, limit=n)
                title = "Berita Watchlist"
                empty = f"Belum ada berita untuk: {', '.join(tickers)}"
            else:
                items = await repo.latest_news(session, limit=n)
                title = f"{n} Berita Terbaru"
                empty = "Belum ada berita."
            if not items:
                reply = empty
            else:
                parts = [f"📰 <b>{title}</b>"]
                for it in items:
                    tix = ", ".join(it["tickers"])
                    head = f"<b>{html.escape(tix)}</b> — " if tix else ""
                    block = (
                        f"\n• {head}{html.escape(it['title'])}"
                        f"\n  <i>{html.escape(it['source'])}</i>"
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
    if not _token():
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
