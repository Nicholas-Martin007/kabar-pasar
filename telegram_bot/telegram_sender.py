"""
Outbound alert pipe.

Formatting + delivery only — this module decides *how* an alert looks and sends
it. It does not decide *who* gets it; `filters.py` owns that, and
`telegram_service.dispatch_alerts` wires the two together.

Split out from telegram_service.py so the broadcast path is separable from the
command/long-poll half, which has grown large.
"""

import html
import logging
from typing import Any, Dict, Optional

from backend.models.news import News

from .telegram_service import send_message, send_photo

logger = logging.getLogger(__name__)

_IMPORTANCE_ICON = {"high": "🔴", "medium": "🔵", "low": "⚪"}


def format_news_alert(item: News) -> str:
    """Title, source, summary and link as Telegram HTML."""
    icon = _IMPORTANCE_ICON.get(item.importance.value, "🔵")
    parts = [f"{icon} <b>{html.escape(item.title)}</b>", f"<i>{html.escape(item.source.value)}</i>"]

    # Prefer AI bullets when present; fall back to the excerpt. The AI path is
    # dormant (no API key) so in practice this is the excerpt today.
    if item.ai_summary:
        parts.append("")
        parts += [f"• {html.escape(b)}" for b in item.ai_summary[:3]]
    elif item.excerpt:
        parts += ["", html.escape(item.excerpt[:300])]

    if item.tickers:
        parts.append("")
        parts.append("📈 " + " ".join(f"<code>{html.escape(t)}</code>" for t in item.tickers[:6]))
    if item.url:
        parts += ["", f'<a href="{html.escape(item.url, quote=True)}">Baca selengkapnya →</a>']
    return "\n".join(parts)


async def send_news_alert(
    chat_id: str, news_item: News, reply_markup: Optional[dict] = None
) -> bool:
    """Deliver one news alert. Returns True if Telegram accepted it."""
    try:
        await send_message(chat_id, format_news_alert(news_item), reply_markup=reply_markup)
        return True
    except Exception as exc:
        logger.warning(
            "sender.news_failed chat=%s id=%s error=%s", chat_id, news_item.id, exc
        )
        return False


def format_stockpick(pick: Dict[str, Any]) -> str:
    """
    Screener result as Telegram HTML.

    `score` here is a RULE-BASED technical score, not a probability and not an
    LLM conviction rating — the wording deliberately avoids implying either.
    """
    cur = pick.get("currency", "IDR")
    lines = [
        f"⭐ <b>{html.escape(str(pick.get('ticker', '?')))}</b> — skor teknikal "
        f"<b>{pick.get('score', 0)}</b>/100",
        f"<i>per {html.escape(str(pick.get('as_of', '')))}</i>",
        "",
        f"Harga: <b>{pick.get('last_close', 0):,.2f} {cur}</b>",
        f"RSI(14): <b>{pick.get('rsi', 0):.1f}</b>",
    ]
    if pick.get("support") is not None:
        lines.append(f"🟢 Support: {pick['support']:,.2f}")
    if pick.get("resistance") is not None:
        lines.append(f"🔴 Resistance: {pick['resistance']:,.2f}")

    reasons = pick.get("reasons") or []
    if reasons:
        lines += ["", "<b>Alasan</b>"]
        lines += [f"• {html.escape(str(r))}" for r in reasons]

    lines += [
        "",
        "<i>Skor teknikal berbasis aturan (RSI/EMA/support) — bukan prediksi "
        "dan bukan rekomendasi jual/beli.</i>",
    ]
    return "\n".join(lines)


async def send_stockpick_alert(
    chat_id: str, pick_data: Dict[str, Any], image_path: Optional[str] = None
) -> bool:
    """
    Deliver a screener pick, with its TA chart attached when available.

    Falls back to a text-only message if the image is missing or the upload
    fails — losing the picture is better than losing the alert.
    """
    caption = format_stockpick(pick_data)

    if image_path:
        ok = await send_photo(chat_id, image_path, caption=caption)
        if ok:
            return True
        logger.info("sender.photo_fallback_to_text chat=%s", chat_id)

    try:
        await send_message(chat_id, caption)
        return True
    except Exception as exc:
        logger.warning("sender.stockpick_failed chat=%s error=%s", chat_id, exc)
        return False


# ── MSCI high-priority alerts ────────────────────────────────────────────────


def format_msci_alert(item: News) -> str:
    """
    MSCI index-review alert.

    Visually loud on purpose: these force mechanical index-fund flows through
    IDX names on a known date, and the window to reposition is short. The
    loudness is only justified because detection is precise — see
    `scrapers.msci_tracker` on why matching is word-boundary anchored.
    """
    ts = item.published_at
    # Trim the ISO timestamp to minutes; seconds and offset are noise here.
    if "T" in ts:
        ts = ts.replace("T", " ")[:16]

    parts = [
        "🚨🚨 <b>[HIGH PRIORITY] MSCI MARKET ALERT</b> 🚨🚨",
        "",
        f"<b>{html.escape(item.title)}</b>",
        f"<i>{html.escape(item.source.value)} | {html.escape(ts)}</i>",
        "",
    ]

    # Prefer AI bullets when present; the excerpt is the practical fallback
    # since the AI path is dormant on this project.
    if item.ai_summary:
        parts += [f"• {html.escape(b)}" for b in item.ai_summary[:3]]
    elif item.excerpt:
        parts.append(html.escape(item.excerpt[:400]))

    tickers = (
        " ".join(f"<code>{html.escape(t)}</code>" for t in item.tickers[:8])
        if item.tickers
        else "IDX Equities"
    )
    parts += ["", f"📊 <b>Saham terdampak:</b> {tickers}"]

    if item.url:
        parts += ["", f"🔗 {html.escape(item.url)}"]

    parts += [
        "",
        "<i>Rebalancing MSCI menggerakkan arus dana indeks secara mekanis. "
        "Informasi, bukan rekomendasi jual/beli.</i>",
    ]
    return "\n".join(parts)


async def send_msci_alert(chat_id: str, item: News) -> bool:
    try:
        await send_message(chat_id, format_msci_alert(item))
        return True
    except Exception as exc:
        logger.warning("sender.msci_failed chat=%s error=%s", chat_id, exc)
        return False


def format_msci_reminder(review_name: str, announcement: str, days_out: int) -> str:
    """Calendar heads-up ahead of a scheduled MSCI review."""
    when = "HARI INI" if days_out == 0 else f"dalam {days_out} hari"
    head = "🚨 <b>MSCI REVIEW HARI INI</b>" if days_out == 0 else "📅 <b>MSCI REVIEW MENDEKAT</b>"
    return "\n".join([
        head,
        "",
        f"<b>{html.escape(review_name)}</b>",
        f"Pengumuman: <b>{html.escape(announcement)}</b> ({when})",
        "",
        "Rebalancing MSCI memicu arus beli/jual mekanis dari dana indeks pada "
        "saham yang masuk atau keluar.",
        "",
        "<i>Tanggal dari kalender resmi MSCI dan dapat berubah — konfirmasi ke "
        "pengumuman resmi. Informasi, bukan rekomendasi.</i>",
    ])


# ── IHSG daily overview ──────────────────────────────────────────────────────

_STATUS_ICON = {
    "BULLISH": "🟢",
    "BEARISH": "🔴",
    "SIDEWAYS / CONSOLIDATION": "🟡",
}


def format_ihsg_overview(o: Dict[str, Any]) -> str:
    """Daily IHSG prospect digest. Takes `IHSGOverview.to_dict()`."""
    icon = _STATUS_ICON.get(o.get("ihsg_status", ""), "🟡")
    chg = o.get("change_percent")
    chg_txt = f"{chg:+.2f}%" if chg is not None else "n/a"

    parts = [
        f"{icon} <b>IHSG — Prospek Harian</b>",
        f"<i>per {html.escape(str(o.get('as_of', '')))}</i>",
        "",
        f"Penutupan: <b>{o.get('last_close', 0):,.2f}</b> ({chg_txt})",
        f"Status: <b>{html.escape(str(o.get('ihsg_status', '')))}</b>",
        "",
        "<b>Level kunci</b>",
    ]
    sup, res = o.get("ihsg_support"), o.get("ihsg_resistance")
    parts.append(f"🟢 Support: <b>{sup:,.2f}</b>" if sup else "🟢 Support: <i>belum terbentuk</i>")
    parts.append(f"🔴 Resistance: <b>{res:,.2f}</b>" if res else "🔴 Resistance: <i>belum terbentuk</i>")

    ema20, ema50, ema200 = o.get("ema20"), o.get("ema50"), o.get("ema200")
    rsi = o.get("rsi")
    parts += ["", "<b>Teknikal</b>"]
    if ema20 and ema50:
        parts.append(f"• EMA20 {ema20:,.2f} · EMA50 {ema50:,.2f}" + (f" · EMA200 {ema200:,.2f}" if ema200 else ""))
    if rsi is not None:
        parts.append(f"• RSI(14) {rsi:.0f}")
    hist = o.get("macd_histogram")
    if hist is not None:
        parts.append(f"• MACD histogram {hist:+.2f}")

    cats = [c for c in (o.get("catalysts") or []) if c.get("changePercent") is not None]
    if cats:
        parts += ["", "<b>Katalis makro</b>"]
        for c in cats[:6]:
            arrow = "🔺" if c["changePercent"] >= 0 else "🔻"
            parts.append(
                f"{arrow} {html.escape(c['name'])}: {c['price']:,.2f} "
                f"({c['changePercent']:+.2f}%)"
            )

    summary = o.get("market_prospect_summary")
    if summary:
        parts += ["", "<b>Prospek</b>", html.escape(summary)]

    # Say plainly that foreign flow is missing. Silence would read as "flat".
    if not o.get("foreign_flow_available"):
        parts += [
            "",
            "ℹ️ <i>Data net foreign flow (bandarmologi) tidak tersedia dari "
            "sumber gratis — tidak ditampilkan daripada ditebak.</i>",
        ]

    for w in (o.get("warnings") or []):
        parts.append(f"⚠️ <i>{html.escape(w)}</i>")

    parts += ["", f"<i>{html.escape(str(o.get('disclaimer', '')))}</i>"]
    return "\n".join(parts)


async def send_ihsg_overview(chat_id: str, overview: Dict[str, Any]) -> bool:
    try:
        await send_message(chat_id, format_ihsg_overview(overview))
        return True
    except Exception as exc:
        logger.warning("sender.ihsg_failed chat=%s error=%s", chat_id, exc)
        return False
