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
import json
import logging
import re
import os
import secrets
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx

from backend.db import repository as repo
from backend.db.session import get_session
from backend.models.news import News

logger = logging.getLogger(__name__)

_API = "https://api.telegram.org/bot{token}/{method}"

# Telegram rejects photo captions longer than this outright (not truncates).
_CAPTION_LIMIT = 1024

# Article ids already alerted on, so two producers can't double-notify (see
# dispatch_alerts). Bounded and insertion-ordered — a plain set would grow
# without limit in a long-running process.
_ALERTED_MAX = 5000
_alerted_ids: "OrderedDict[str, None]" = OrderedDict()


def _remember_alerted(news_id: str) -> None:
    _alerted_ids[news_id] = None
    while len(_alerted_ids) > _ALERTED_MAX:
        _alerted_ids.popitem(last=False)  # drop oldest


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
    "/important on — hanya berita PENTING · /important off\n"
    "/all off — berhenti terima semua · /all on — terima semua lagi\n\n"
    "<b>Mode pilihan</b> (saat /all off)\n"
    "/watch BBCA — hanya saham tertentu\n"
    "/follow emas — hanya topik tertentu\n"
    "/unwatch · /unfollow — kebalikannya\n\n"
    "<b>Analisis</b>\n"
    "/ihsg — prospek harian IHSG + chart\n"
    "/chart BBCA — chart teknikal harian + level TP/SL\n"
    "/chart IHSG · /chart EMAS · /chart USDIDR — indeks &amp; komoditas\n\n"
    "<b>Lainnya</b>\n"
    "/news 15 — tampilkan N berita terbaru (default 10)\n"
    "/digest — ringkasan berita hari ini\n"
    "/testnews — kirim contoh notifikasi berita asli\n"
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


async def send_photo(
    chat_id: str,
    photo_path: str,
    caption: str = "",
    reply_markup: Optional[dict] = None,
) -> bool:
    """
    Upload a local image via multipart. Returns True on success.

    Separate from `_post` because sendPhoto needs multipart/form-data, not JSON.
    Telegram *rejects* captions over 1024 chars rather than trimming them, and a
    full TA rationale runs longer than that — so the photo carries a trimmed
    caption and the complete text follows as a normal message instead of being
    silently lost.
    """
    if not _token():
        return False

    path = Path(photo_path)
    if not path.is_file():
        logger.warning("telegram.photo_missing path=%s", photo_path)
        return False

    # When the text is too long for a caption, the photo carries a SHORT header
    # only and the analysis follows once as its own message. Previously the
    # photo carried a truncated copy AND the full text followed, so the reader
    # saw the same analysis twice — once cut off mid-sentence.
    overflow = len(caption) > _CAPTION_LIMIT
    if overflow:
        short = _caption_header(caption)
    else:
        short = caption

    url = _API.format(token=_token(), method="sendPhoto")
    data = {"chat_id": chat_id, "parse_mode": "HTML"}
    if short:
        data["caption"] = short
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)

    try:
        with path.open("rb") as fh:
            files = {"photo": (path.name, fh, "image/png")}
            # Uploads are slower than JSON calls — a 150 KB PNG on a poor
            # connection needs more than the usual 15s.
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(url, data=data, files=files)
                resp.raise_for_status()
    except Exception as exc:
        logger.warning("telegram.photo_failed path=%s error=%s", path.name, exc)
        return False

    if overflow:
        await send_message(chat_id, caption)
    logger.info("telegram.photo_sent chat=%s file=%s", chat_id, path.name)
    return True


async def send_chart(chat_id: str, ticker: str) -> bool:
    """
    Generate the TA chart for `ticker` and deliver rationale + PNG.

    Imported lazily: ta_engine pulls in matplotlib/pandas, and this module is
    imported at app startup by the poller — no reason to pay that cost unless
    someone actually asks for a chart.
    """
    from backend.services.chart_service import get_chart_with_rationale

    try:
        result, rationale = await get_chart_with_rationale(ticker)
    except ValueError as exc:
        await send_message(chat_id, f"⚠️ {html.escape(str(exc))}")
        return False
    except Exception as exc:
        logger.warning("telegram.chart_failed ticker=%s error=%s", ticker, exc)
        await send_message(chat_id, "⚠️ Gagal membuat chart. Coba lagi sebentar lagi.")
        return False

    ok = await send_photo(chat_id, result.chart_path, caption=rationale)
    if not ok:
        # Image failed but the analysis is still worth delivering.
        await send_message(chat_id, rationale)
    return ok


_TAG_RE = re.compile(r"<(/?)([a-zA-Z]+)[^>]*>")


def _caption_header(text: str) -> str:
    """
    First couple of lines of an over-long body, as the photo's caption.

    Just enough to identify the image (ticker + date). The full analysis arrives
    as the single message that follows, so nothing is duplicated and nothing is
    cut off mid-sentence.
    """
    head: List[str] = []
    for line in text.splitlines():
        if not line.strip():
            if head:
                break
            continue
        head.append(line)
        if len(head) >= 2:
            break
    return _trim_html("\n".join(head), _CAPTION_LIMIT)


def _trim_html(text: str, limit: int) -> str:
    """
    Truncate HTML to `limit` chars without leaving broken markup.

    A plain slice is not safe with parse_mode=HTML: Telegram answers 400 and
    rejects the whole message if a tag is left open or cut in half. That failure
    is invisible in normal use because callers fall back to a text message — the
    photo just silently stops being attached for any caption over the limit.

    Cuts back off a partial tag, then closes whatever is still open, innermost
    first.
    """
    if len(text) <= limit:
        return text

    # Reserve room for the ellipsis plus a few closing tags.
    cut = max(0, limit - 24)
    lt, gt = text.rfind("<", 0, cut), text.rfind(">", 0, cut)
    if lt > gt:            # the cut landed inside a tag — back up to before it
        cut = lt
    head = text[:cut].rstrip()

    open_tags: List[str] = []
    for m in _TAG_RE.finditer(head):
        closing, name = m.group(1), m.group(2).lower()
        if closing:
            if open_tags and open_tags[-1] == name:
                open_tags.pop()
        else:
            open_tags.append(name)

    return head + "…" + "".join(f"</{t}>" for t in reversed(open_tags))


async def send_ihsg_report(chat_id: str) -> bool:
    """
    Deliver the IHSG daily prospect: the ^JKSE chart with the market overview
    as its caption.

    The overview text runs past Telegram's 1024-char caption limit, so the
    chart carries a trimmed caption and `send_photo` follows up with the full
    text — otherwise the tail (levels, catalysts, prospect) would be silently
    dropped by Telegram rather than truncated visibly.

    Imports are lazy for the same reason as `send_chart`: this module loads at
    startup for the poller and shouldn't drag in matplotlib/pandas.
    """
    from backend.services.chart_service import get_chart
    from backend.services.ihsg_engine import build_ihsg_overview

    from .telegram_sender import format_ihsg_overview

    try:
        overview = await build_ihsg_overview()
        caption = format_ihsg_overview(overview.to_dict())
    except Exception as exc:
        logger.warning("telegram.ihsg_overview_failed error=%s", exc)
        await send_message(chat_id, "⚠️ Gagal menyiapkan ringkasan IHSG.")
        return False

    # The chart is a bonus — if rendering fails the numbers still go out.
    try:
        result = await get_chart("^JKSE")
        ok = await send_photo(chat_id, result.chart_path, caption=caption)
        if ok:
            return True
        logger.info("telegram.ihsg_photo_fallback chat=%s", chat_id)
    except Exception as exc:
        logger.warning("telegram.ihsg_chart_failed error=%s", exc)

    await send_message(chat_id, caption)
    return True


async def send_message(
    chat_id: str, text: str, reply_markup: Optional[dict] = None
) -> None:
    if not _token():
        return
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    await _post("sendMessage", payload)


async def _answer_callback(callback_id: str, text: str = "") -> None:
    await _post("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})


def _in_quiet_hours() -> bool:
    """QUIET_HOURS env like '22-6' (WIB). Suppresses push (not command replies)."""
    raw = os.getenv("QUIET_HOURS", "").strip()
    if "-" not in raw:
        return False
    try:
        start, end = (int(x) for x in raw.split("-", 1))
    except ValueError:
        return False
    if start == end:
        return False
    hour = (datetime.now(timezone.utc) + timedelta(hours=7)).hour
    return start <= hour < end if start < end else (hour >= start or hour < end)


def _alert_buttons(source: str, url: Optional[str]) -> dict:
    """Inline keyboard: open article + mute this source."""
    rows = []
    if url:
        rows.append([{"text": "📰 Buka", "url": url}])
    rows.append(
        [{"text": f"🔇 Mute {source}", "callback_data": f"mute:{source.lower()}"}]
    )
    return {"inline_keyboard": rows}


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


def _base_match(sub: dict, hay: str, tickers) -> bool:
    """Firehose (minus mutes) OR watchlist tickers OR followed keywords."""
    if sub.get("all_news"):
        return not any(m in hay for m in (sub.get("mute") or []))
    if set(sub.get("tickers") or []).intersection(tickers or []):
        return True
    keywords = sub.get("keywords") or []
    return any(kw in hay for kw in keywords) if keywords else False


def _source_allowed(sub: dict, source_value: str) -> bool:
    """
    Source allow-list from the app's control panel.

    An EMPTY list means "all sources", not "none" — otherwise every existing
    subscriber would go silent the moment the column was added.
    """
    allowed = sub.get("sources") or []
    return True if not allowed else source_value in allowed


def _matches(sub: dict, item: News) -> bool:
    # MSCI reviews bypass every content filter. They move index-fund flows
    # mechanically on a known date, so a watchlist or high-only setting
    # shouldn't hide one. The master `news_alerts` switch below still wins —
    # a user who turned news off entirely gets nothing, which is consent, not
    # a filter. Detection is precise enough for this to be safe; see
    # scrapers.msci_tracker.
    if not sub.get("news_alerts", True):
        return False
    if getattr(item, "is_msci_alert", False):
        return True
    if not _source_allowed(sub, item.source.value):
        return False
    hay = f"{item.title} {item.excerpt} {item.source.value}".lower()
    if not _base_match(sub, hay, item.tickers):
        return False
    if sub.get("high_only") and item.importance.value != "high":
        return False
    return True


def matches_stockpick(sub: dict, pick: dict) -> bool:
    """
    Whether a screener pick should reach this subscriber.

    Opt-in (defaults off) and gated on the control panel's RSI threshold —
    `min_rsi` is an upper bound here because the screener hunts oversold names,
    so "min RSI 40" means "only show me things at RSI <= 40".
    """
    if not sub.get("stockpick_alerts", False):
        return False
    if _in_quiet_hours():
        return False
    threshold = int(sub.get("min_rsi", 100) or 100)
    if float(pick.get("rsi", 0)) > threshold:
        return False
    watch = set(sub.get("tickers") or [])
    if watch:
        # Strip the .JK suffix so a watchlist of "BBCA" matches "BBCA.JK".
        base = str(pick.get("ticker", "")).split(".")[0].upper()
        return base in watch or str(pick.get("ticker", "")).upper() in watch
    return True


def _format_alert_dict(item: dict) -> str:
    """Single-item alert format from a DB news row (same look as live alerts)."""
    tickers = item.get("tickers") or []
    head = ", ".join(tickers) if tickers else item["source"]
    icon = "📈" if tickers else "📰"
    lines = [f"{icon} <b>{html.escape(head)}</b>", html.escape(item["title"])]
    if tickers:
        lines.append(f"<i>{html.escape(item['source'])}</i>")
    if item.get("url"):
        lines.append(item["url"])
    return "\n".join(lines)


def _matches_dict(sub: dict, item: dict) -> bool:
    """Dict-based variant of _matches for digest (news rows from the DB)."""
    hay = f"{item['title']} {item['source']}".lower()
    if not _base_match(sub, hay, item.get("tickers")):
        return False
    if sub.get("high_only") and item.get("importance") != "high":
        return False
    return True


_IMPORTANCE_RANK = {"high": 0, "medium": 1, "low": 2}


def _format_digest(items: List[dict]) -> str:
    wib = datetime.now(timezone.utc) + timedelta(hours=7)
    parts = [f"📊 <b>Ringkasan Pasar — {wib.strftime('%d/%m/%Y %H:%M')} WIB</b>"]
    for it in items:
        tix = ", ".join(it.get("tickers") or [])
        head = f"<b>{html.escape(tix)}</b> — " if tix else ""
        flag = "🔴 " if it.get("importance") == "high" else ""
        block = (
            f"\n{flag}• {head}{html.escape(it['title'])}"
            f"\n  <i>{html.escape(it['source'])}</i>"
        )
        if it.get("url"):
            block += f"\n  {it['url']}"
        parts.append(block)

    # Every digest carries the index-review calendar. MSCI and FTSE are the one
    # recurring market event whose date is knowable in advance and whose flows
    # are mechanical, so a user should never be caught out by one. A line of
    # text daily is cheap; a missed repositioning window is not.
    try:
        from scrapers.msci_tracker import calendar_snapshot

        from .telegram_sender import format_index_calendar

        cal = format_index_calendar(calendar_snapshot())
        if cal:
            parts.append("\n" + cal)
    except Exception as exc:
        # A calendar failure must never cost the user their news digest.
        logger.warning("telegram.digest_calendar_failed error=%s", exc)

    return "\n".join(parts)


_test_news_idx = 0


async def send_test_news() -> int:
    """
    Testing only: push one REAL cached news item (rotating) to all subscribers,
    so you can verify news delivery without waiting for genuinely-new articles.
    """
    global _test_news_idx
    if not _token():
        return 0
    async with get_session() as session:
        subs = await repo.list_subscribers(session)
        recent = await repo.latest_news(session, limit=50)
    if not subs:
        return 0
    sent = 0
    for sub in subs:
        # Respect the subscriber's filter (all-news/mute or watchlist/topics).
        pool = [it for it in recent if _matches_dict(sub, it)]
        if not pool:
            await send_message(
                sub["chat_id"],
                "ℹ️ Belum ada berita yang cocok dengan filtermu (coba /all on).",
            )
            continue
        item = pool[_test_news_idx % len(pool)]
        await send_message(
            sub["chat_id"],
            _format_alert_dict(item),
            reply_markup=_alert_buttons(item["source"], item.get("url")),
        )
        sent += 1
    _test_news_idx += 1
    return sent


async def dispatch_digest(limit: int = 10) -> int:
    """Send each subscriber a daily summary of news matching their prefs."""
    if not _token() or _in_quiet_hours():
        return 0
    async with get_session() as session:
        subs = await repo.list_subscribers(session)
        recent = await repo.latest_news(session, limit=80)
    sent = 0
    for sub in subs:
        matched = [it for it in recent if _matches_dict(sub, it)]
        # Most important first (stable sort keeps recency within a tier).
        matched.sort(key=lambda it: _IMPORTANCE_RANK.get(it.get("importance"), 1))
        matched = matched[:limit]
        if not matched:
            continue
        await send_message(sub["chat_id"], _format_digest(matched))
        sent += 1
    if sent:
        logger.info("telegram.digest_sent count=%d", sent)
    return sent


async def dispatch_alerts(new_items: List[News]) -> int:
    """
    Push newly-ingested news to subscribers by watchlist / topic / firehose.

    Two producers now call this: the 30s fast poller and the 5-minute scheduled
    refresh. They overlap on Kontan/CNBC/Bloomberg, and although
    `upsert_news_items` normally hands each article to only one of them, the
    read-then-insert isn't atomic — a narrow interleave could show the same item
    to both. A duplicate DB row is harmless (the PK rejects it); a duplicate
    Telegram alert is what the user would actually notice. The in-memory guard
    below makes alerting idempotent per article regardless of caller.
    """
    if not _token() or not new_items or _in_quiet_hours():
        return 0

    fresh = [n for n in new_items if n.id not in _alerted_ids]
    if not fresh:
        return 0
    for n in fresh:
        _remember_alerted(n.id)
    new_items = fresh

    async with get_session() as session:
        subscribers = await repo.list_subscribers(session)

    sent = 0
    for sub in subscribers:
        matched = [n for n in new_items if _matches(sub, n)]
        for item in matched[:_ALERTS_PER_CYCLE]:
            await send_message(
                sub["chat_id"],
                _format_alert(item),
                reply_markup=_alert_buttons(item.source.value, item.url),
            )
            sent += 1
    if sent:
        logger.info("telegram.alerts_sent count=%d", sent)
    return sent


# ── Command handling + long-poll loop ─────────────────────────────────────────

async def _handle_command(chat_id: str, text: str) -> None:
    parts = text.strip().split()
    cmd = parts[0].lower().lstrip("/").split("@")[0]
    arg = parts[1].upper() if len(parts) > 1 else ""

    # Handled before the DB session opens: rendering takes seconds and there's
    # no reason to hold a session across it.
    if cmd == "chart":
        if not arg:
            await send_message(
                chat_id,
                "Format: <code>/chart BBCA</code>\n"
                "Indeks & komoditas juga bisa: <code>/chart IHSG</code>, "
                "<code>/chart EMAS</code>, <code>/chart USDIDR</code>",
            )
            return
        # resolve_symbol handles IHSG/EMAS-style aliases and only appends ".JK"
        # to things that actually look like IDX tickers.
        from ta_engine.price_utils import resolve_symbol

        symbol = resolve_symbol(arg)
        await send_message(chat_id, f"⏳ Membuat chart {html.escape(symbol)}…")
        await send_chart(chat_id, symbol)
        return

    if cmd in ("msci", "ftse", "indeks"):
        await send_index_digest(chat_id)
        return

    if cmd == "ihsg":
        await send_message(chat_id, "⏳ Menyiapkan ringkasan IHSG…")
        await send_ihsg_report(chat_id)
        return

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
        elif cmd == "important":
            on = arg.lower() in ("on", "1", "ya", "true", "")  # bare /important = on
            await repo.set_subscriber_high_only(session, chat_id, on)
            reply = (
                "🔴 Hanya berita PENTING: AKTIF. Hanya berita high-importance dikirim."
                if on
                else "⚪ Hanya berita penting: NONAKTIF. Semua tingkat dikirim."
            )
        elif cmd == "list":
            sub = await repo.get_subscriber(session, chat_id)
            if not sub:
                reply = "Belum mulai. Kirim /start untuk menerima semua berita."
            else:
                reply = (
                    f"📋 <b>Pengaturanmu</b>\n"
                    f"Semua berita: {'AKTIF' if sub['all_news'] else 'nonaktif'}\n"
                    f"Hanya berita penting: {'AKTIF 🔴' if sub.get('high_only') else 'nonaktif'}\n"
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
        elif cmd == "digest":
            sub = await repo.get_subscriber(session, chat_id) or {"all_news": True}
            recent = await repo.latest_news(session, limit=80)
            matched = [it for it in recent if _matches_dict(sub, it)][:10]
            reply = (
                _format_digest(matched)
                if matched
                else "Belum ada berita untuk ringkasan hari ini."
            )
        elif cmd == "link":
            code = new_link_code(chat_id)
            reply = (
                f"🔗 Kode tautan: <b>{code}</b>\n"
                "Masukkan di app Kabar Pasar (Profil → Hubungkan Telegram) "
                "dalam 10 menit. Watchlist app-mu akan otomatis tersinkron."
            )
        elif cmd == "test":
            reply = "🔔 Tes notifikasi berhasil! Bot aktif dan terhubung. ✅"
        elif cmd == "testnews":
            sub = await repo.get_subscriber(session, chat_id) or {"all_news": True}
            recent = await repo.latest_news(session, limit=50)
            matched = [it for it in recent if _matches_dict(sub, it)][:3]
            if not matched:
                reply = (
                    "Belum ada berita yang cocok dengan pengaturanmu. "
                    "Coba /all on, atau /watch BBCA."
                )
            else:
                for it in matched:
                    await send_message(chat_id, _format_alert_dict(it))
                reply = f"✅ {len(matched)} contoh berita dikirim (format notifikasi asli)."
        elif cmd == "stop":
            await repo.remove_subscriber(session, chat_id)
            reply = "🛑 Berhenti. Kamu tidak akan menerima notifikasi lagi."
        else:
            reply = HELP

    await send_message(chat_id, reply)


async def _handle_callback(cq: dict) -> None:
    """Handle inline-button taps (e.g. mute a source)."""
    data = cq.get("data", "")
    cq_id = cq.get("id", "")
    chat_id = str((cq.get("message") or {}).get("chat", {}).get("id", ""))
    if data.startswith("mute:") and chat_id:
        topic = data.split(":", 1)[1].strip()
        async with get_session() as session:
            await repo.add_subscriber_mute(session, chat_id, topic)
        await _answer_callback(cq_id, f"🔇 Dibisukan: {topic}")
    else:
        await _answer_callback(cq_id)


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
                cq = upd.get("callback_query")
                if cq:
                    await _handle_callback(cq)
                    continue
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


# ── Index review (MSCI / FTSE) ───────────────────────────────────────────────


async def dispatch_index_reminders() -> int:
    """
    Push MSCI/FTSE review reminders that are due today.

    Runs once a day. `due_reminders()` only returns a review at exactly T-3 or
    on the day itself, so this is silent on every other date — the scheduling
    is a daily *check*, not a daily message.

    This job is the piece that was missing: the calendar, the due-date logic and
    the formatter all existed, but nothing ever called them, so no reminder had
    ever actually been sent.
    """
    from scrapers.msci_tracker import due_reminders

    from .telegram_sender import format_msci_reminder

    if not _token():
        return 0

    due = due_reminders()
    if not due:
        logger.info("telegram.index_reminders none_due")
        return 0

    async with get_session() as session:
        subs = await repo.list_subscribers(session)

    sent = 0
    for sub in subs:
        # Gated on the master news switch only. A calendar date is not a stock
        # tip, so watchlist and high-only filters should not hide it — but a
        # user who turned notifications off entirely still gets nothing.
        if not sub.get("news_alerts", True):
            continue
        for item in due:
            r = item["review"]
            try:
                await send_message(
                    str(sub["chat_id"]),
                    format_msci_reminder(
                        r.name, r.announcement.isoformat(), item["days_out"]
                    ),
                )
                sent += 1
            except Exception as exc:
                logger.warning("telegram.index_reminder_failed error=%s", exc)

    logger.info("telegram.index_reminders sent=%d due=%d", sent, len(due))
    return sent


async def send_index_digest(chat_id: str, limit: int = 8) -> bool:
    """
    On-demand MSCI/FTSE view: flagged headlines plus the upcoming calendar.

    Exists because index news was reaching the database but had no surface —
    items flagged by the backfill were never "new at ingest", so the alert path
    never saw them and they stayed invisible.
    """
    from scrapers.msci_tracker import calendar_snapshot

    from .telegram_sender import format_index_calendar

    try:
        async with get_session() as session:
            rows = await repo.query_index_news(session, limit=limit)
    except Exception as exc:
        logger.warning("telegram.index_digest_failed error=%s", exc)
        await send_message(chat_id, "⚠️ Gagal mengambil berita indeks.")
        return False

    parts = ["🌐 <b>Berita MSCI &amp; FTSE</b>", ""]
    if rows:
        for n in rows:
            when = str(n.get("published_at") or "")[:10]
            title = html.escape(str(n.get("title") or ""))
            url = n.get("url")
            body = f'<a href="{html.escape(str(url))}">{title}</a>' if url else title
            src = f" <i>· {html.escape(str(n.get('source') or ''))}</i>"
            parts.append(f"🚨 <b>{when}</b> {body}{src}")
    else:
        parts.append("<i>Belum ada berita MSCI/FTSE di cache.</i>")

    cal = format_index_calendar(calendar_snapshot())
    if cal:
        parts += ["", cal]

    await send_message(chat_id, "\n".join(parts))
    return True
