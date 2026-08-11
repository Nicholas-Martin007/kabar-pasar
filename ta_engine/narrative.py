"""
Plain-language Indonesian summary of a ChartResult.

Deliberately rule-based, not LLM-generated: ANTHROPIC_API_KEY is intentionally
empty on this project (no paid AI), so an "AI rationale" would simply fail. These
rules are deterministic, free, and auditable — you can point at the exact
threshold that produced any sentence, which matters when the output sits next to
price levels.

Describes what the indicators SAY. It does not tell anyone to buy or sell; the
disclaimer travels with it.
"""

import html
from typing import TYPE_CHECKING, List, Optional

from .pattern_detector import explain_pattern
from .price_utils import format_price

if TYPE_CHECKING:  # avoid a circular import at runtime
    from .chart_generator import ChartResult

# Section divider. Plain rule rather than emoji so it reads as structure,
# not decoration, and stays legible in Telegram's narrow column.
_DIV = "━━━━━━━━━━━━━━━━━━━━"

# Wilder's conventional RSI thresholds.
_RSI_OVERBOUGHT = 70
_RSI_OVERSOLD = 30


def _rsi_phrase(rsi: float) -> str:
    if rsi >= _RSI_OVERBOUGHT:
        return f"RSI {rsi:.0f} — wilayah <b>overbought</b>, momentum beli sudah panas"
    if rsi <= _RSI_OVERSOLD:
        return f"RSI {rsi:.0f} — wilayah <b>oversold</b>, tekanan jual sudah dalam"
    if rsi >= 55:
        return f"RSI {rsi:.0f} — momentum condong <b>positif</b>"
    if rsi <= 45:
        return f"RSI {rsi:.0f} — momentum condong <b>negatif</b>"
    return f"RSI {rsi:.0f} — momentum <b>netral</b>"


def _trend_phrase(close: float, ema20: float, ema50: float) -> str:
    if ema20 > ema50 and close > ema20:
        return "Harga di atas EMA20 &amp; EMA20 di atas EMA50 — struktur tren <b>naik</b>"
    if ema20 < ema50 and close < ema20:
        return "Harga di bawah EMA20 &amp; EMA20 di bawah EMA50 — struktur tren <b>turun</b>"
    if ema20 > ema50:
        return "EMA20 masih di atas EMA50, tapi harga tertahan di bawah EMA20 — tren naik <b>melemah</b>"
    return "EMA20 di bawah EMA50 sementara harga mencoba naik — potensi <b>pembalikan</b>, belum terkonfirmasi"


_STRENGTH_ICON = {"KUAT": "🟩", "SEDANG": "🟨", "LEMAH": "⬜"}


def _stoch_lines(result: "ChartResult") -> List[str]:
    """
    Stochastic reading, with the %K/%D relationship spelled out.

    Deliberately says what it measures. Read as "overbought = sell" it is
    actively harmful: in a strong trend stochastic pins above 80 for weeks and
    every reading is a losing short. It describes position within the recent
    range, nothing more.
    """
    k, d = result.stoch_k, result.stoch_d
    if k is None or d is None:
        return []

    if k >= 80:
        state = "di zona jenuh beli (overbought)"
    elif k <= 20:
        state = "di zona jenuh jual (oversold)"
    else:
        state = "di tengah rentang"

    cross = "%K di atas %D — momentum jangka pendek naik" if k > d else (
        "%K di bawah %D — momentum jangka pendek turun"
    )
    lines = [f"• Stochastic %K {k:.0f} / %D {d:.0f} — {state}; {cross}"]
    if k >= 80 or k <= 20:
        lines.append(
            "  <i>Catatan: dalam tren kuat, stochastic bisa menempel di zona "
            "jenuh berminggu-minggu. Ini ukuran posisi harga dalam rentangnya, "
            "bukan aba-aba beli/jual.</i>"
        )
    return lines


def _zone_lines(
    icon: str,
    name: str,
    zone: Optional[dict],
    fallback: Optional[float],
    cur: str,
) -> List[str]:
    """
    Render one S/R zone as band + strength + the evidence behind the strength.

    The evidence line is not decoration. "KUAT" on its own is a claim the reader
    has to take on trust; "9 tes · 7 bertahan · 2 jebol" is the actual finding,
    and it lets someone disagree with the label. It also keeps the wording
    honest — a level described as strong that broke twice says so out loud.
    """
    if not zone:
        if fallback is not None:
            return [f"{icon} {name}: <b>{format_price(fallback, cur)}</b>"]
        return [f"{icon} {name}: <i>tidak terdeteksi</i>"]

    lo, hi = zone["low"], zone["high"]
    band = (
        format_price(lo, cur) if lo == hi
        else f"{format_price(lo, cur)}–{format_price(hi, cur)}"
    )
    mark = _STRENGTH_ICON.get(zone["label"], "")
    return [
        f"{icon} {name}: <b>{band}</b> · {mark} <b>{zone['label']}</b>",
        f"   <i>{zone['evidence']}</i>",
    ]


def build_rationale(result: "ChartResult") -> str:
    """HTML-formatted (Telegram parse_mode=HTML) technical summary."""
    cur = result.currency
    lines: List[str] = [
        f"📊 <b>{result.ticker}</b> — analisis teknikal harian",
        f"<i>per {result.as_of}</i>",
        "",
        f"Harga terakhir: <b>{format_price(result.last_close, cur)} {cur}</b>",
        f"• {_trend_phrase(result.last_close, result.ema20, result.ema50)}",
        f"• {_rsi_phrase(result.rsi)}",
        *_stoch_lines(result),
        f"• ATR(14) {format_price(result.atr, cur)} — ukuran volatilitas harian",
        "",
        _DIV,
        "<b>Level kunci</b>",
    ]

    lines += _zone_lines("🟢", "Support", result.support_zone, result.support, cur)
    lines += _zone_lines("🔴", "Resistance", result.resistance_zone, result.resistance, cur)
    lines.append(
        "<i>KUAT/SEDANG/LEMAH = seberapa banyak bukti di level itu (jumlah tes, "
        "berapa kali bertahan, seberapa baru, volume yang transaksi di sana). "
        "Ini BUKAN peluang level akan bertahan — support kuat pun bisa jebol.</i>"
    )

    # Mirror the chart's sentiment badge. Without this the image says
    # "WARNING / BEARISH" while the caption beside it says nothing, and the
    # reader has to reconcile the two.
    if result.pattern_detected and result.pattern_name:
        icon = {"BULLISH": "🟢", "BEARISH_WARNING": "🔴"}.get(result.sentiment, "🟡")
        bias = {
            "BULLISH": "condong BULLISH",
            "BEARISH_WARNING": "condong BEARISH",
        }.get(result.sentiment, "arah BELUM tentu")
        tf = result.selected_timeframe.upper()
        lines += [
            "",
            _DIV,
            f"{icon} <b>Pola: {result.pattern_name}</b> — {bias}",
            f"<i>{tf} · kemiripan bentuk {result.quality_score * 100:.0f}% "
            f"(serapi apa bentuknya, bukan peluang berhasil)</i>",
        ]

        # Spell the pattern out. A name and a target with no explanation gives
        # the reader nothing to judge, and no way to see that the projection is
        # CONDITIONAL on a breakout that has not happened yet.
        guide = explain_pattern(result.pattern_name)
        if guide:
            lines += [
                "",
                f"📖 <b>Apa ini:</b> {guide['what']}",
                f"↗️ <b>Biasanya:</b> {guide['usually']}",
                f"✅ <b>Valid kalau:</b> {guide['confirm']}",
                f"❌ <b>Batal kalau:</b> {guide['invalid']}",
            ]

        # Status FIRST, then the projection — and only if the projection still
        # stands. Printing "BELUM terjadi" under a pattern price has already
        # broken out of, the wrong way, is the single most misleading thing this
        # message could say.
        res = result.pattern_resolution
        gap = result.pattern_resolution_atr
        if result.pattern_invalidated:
            way = "ATAS" if res == "broke_up" else "BAWAH"
            lines += [
                "",
                f"🚫 <b>Pola ini sudah BATAL.</b> Harga menembus ke {way} batas "
                f"pola sejauh {gap:.1f}× ATR, berlawanan dengan arah polanya.",
                "<i>Target measured move dari pola ini sudah tidak berlaku dan "
                "tidak ditampilkan. Level TP/SL di bawah dihitung dari ATR dan "
                "struktur support/resistance — bukan dari pola ini — jadi tetap "
                "berlaku. Pola tetap ditampilkan supaya kamu bisa melihat apa "
                "yang gagal.</i>",
            ]
        elif res in ("broke_up", "broke_down"):
            way = "atas" if res == "broke_up" else "bawah"
            lines += [
                "",
                f"⚡ <b>Sudah tembus.</b> Harga menembus batas {way} pola "
                f"({gap:.1f}× ATR) — pola sudah aktif, bukan lagi menunggu.",
            ]
            if result.pattern_target is not None:
                lines.append(
                    f"📐 Measured move mengarah ke "
                    f"<b>{format_price(result.pattern_target, cur)}</b> "
                    f"(target, bukan kepastian)."
                )
        elif result.pattern_breakout is not None and result.pattern_target is not None:
            lines += [
                "",
                f"📐 <b>Proyeksi (BELUM terjadi):</b> kalau tembus "
                f"<b>{format_price(result.pattern_breakout, cur)}</b>, measured move "
                f"mengarah ke <b>{format_price(result.pattern_target, cur)}</b>.",
                "<i>Garis titik-titik di chart adalah proyeksi, bukan harga yang "
                "sudah terjadi. Selama belum tembus, pola ini belum berlaku.</i>",
            ]

        lines.append(
            "<i>⚠️ Pola teknikal sering gagal. Breakout bisa berbalik (false "
            "break), dan target measured move belum tentu tercapai. Ini alat "
            "bantu baca grafik, bukan ramalan harga.</i>"
        )


    # The scenario heading must match the frame. Labelling a breakdown "asumsi
    # posisi BELI" would tell the reader to buy the exact setup the chart is
    # warning about.
    if result.trade_direction == "none":
        lines += [
            "",
            "<i>Indeks tidak bisa dibeli langsung oleh investor ritel, jadi "
            "tidak ada level TP/SL — support &amp; resistance di atas berlaku "
            "sebagai acuan arah pasar.</i>",
        ]
    elif result.tp1 is not None:
        short = result.trade_direction == "short"
        head = (
            "<b>Skenario BEARISH (jika breakdown)</b>" if short
            else "<b>Skenario (asumsi posisi BELI)</b>"
        )
        lines += [
            "",
            _DIV,
            head,
            f"🎯 Target 1: <b>{format_price(result.tp1, cur)}</b>  (1:{result.risk_reward_tp1:g})",
            f"🎯 Target 2: <b>{format_price(result.tp2, cur)}</b>  (1:{result.risk_reward_tp2:g})",
            f"🛑 Invalidasi: <b>{format_price(result.sl, cur)}</b>",
            f"Jarak risiko: {format_price(result.risk_per_share, cur)} {cur} "
            f"({result.risk_per_share / result.last_close:.1%} dari harga)",
        ]
        if short:
            lines.append(
                "<i>Ritel IDX umumnya tidak bisa short — ini acuan risiko "
                "turun &amp; batas invalidasi, bukan ajakan jual.</i>"
            )

    # Where to actually get in. A target and a stop are unusable without it,
    # and the R/R quoted here is recomputed AT the zone — the headline 1:2 was
    # derived from the last close, so reusing it beside a different entry price
    # would be quietly wrong.
    if result.entry_low is not None and result.entry_high is not None:
        lo = format_price(result.entry_low, cur)
        hi = format_price(result.entry_high, cur)
        zone = f"<b>{lo}</b>" if result.entry_low == result.entry_high else f"<b>{lo} – {hi}</b>"
        lines += ["", _DIV, "<b>Rencana masuk</b>", f"🟩 Ideal beli di {zone}"]

        if result.rr_at_entry is not None:
            lines.append(
                f"   Risk/reward di zona ini: <b>1:{result.rr_at_entry:g}</b>"
            )
        if result.breakout_trigger is not None:
            lines.append(
                f"🚀 Atau tambah saat breakout di atas "
                f"<b>{format_price(result.breakout_trigger, cur)}</b>"
            )
        if result.entry_note:
            icon = "⚠️" if result.entry_extended else "ℹ️"
            lines.append(f"{icon} <i>{result.entry_note}</i>")
    elif result.entry_note:
        # Bearish or index: say why there is no buy zone instead of omitting it,
        # so a missing section never reads as an oversight.
        lines += ["", f"<i>{result.entry_note}</i>"]

    # Valuation, so the reader sees whether the chart is attached to a business
    # that earns money. Metrics that failed validation are simply absent — see
    # ta_engine.fundamentals on why bad vendor data is dropped, not shown.
    if result.fundamentals_summary:
        lines += ["", _DIV, "<b>Fundamental</b>", f"🏦 {result.fundamentals_summary}"]
        f = result.fundamentals or {}
        if f.get("suppressed"):
            lines.append(
                f"<i>Tidak ditampilkan ({', '.join(f['suppressed'])}): data "
                f"penyedia di luar rentang wajar.</i>"
            )

    # Momentum divergence — an exhaustion warning, explicitly not a reversal
    # call, because divergence can persist for weeks in a strong trend.
    if result.rsi_divergence:
        d = result.rsi_divergence
        icon = "🔴" if d["direction"] == "bearish" else "🟢"
        lines += [
            "",
            _DIV,
            f"{icon} <b>{d['type']}</b>",
            f"   {d['from']['date']} RSI {d['from']['rsi']:.0f} → "
            f"{d['to']['date']} RSI {d['to']['rsi']:.0f} "
            f"(harga bergerak berlawanan)",
            "<i>Divergensi = peringatan momentum melemah, bukan sinyal balik "
            "arah. Konfirmasi tetap dari harga.</i>",
        ]

    # Recent headlines, shown unconditionally and unfiltered. This used to be
    # gated on a volume spike, which meant most charts carried no news at all —
    # exactly backwards, since the reason to read news beside a chart is
    # conviction, and that matters on quiet days too. Good and bad both appear.
    news = result.recent_news or []
    if news:
        icon = {"high": "🔴", "medium": "🔵", "low": "⚪"}
        lines += ["", _DIV, f"<b>Berita terbaru {result.ticker}</b>"]
        for n in news[:5]:
            dot = icon.get(n.get("importance"), "⚪")
            when = str(n.get("publishedAt") or "")[:10]
            flag = "🚨 " if n.get("isMsciAlert") else ""
            title = html.escape(n.get("title") or "")
            url = n.get("url")
            # Link the headline itself: an <a> keeps the message compact where a
            # bare URL on its own line would double the length of this section.
            body = f'<a href="{html.escape(str(url))}">{title}</a>' if url else title
            src = f" <i>· {html.escape(str(n['source']))}</i>" if n.get("source") else ""
            lines.append(f"{dot} {flag}<b>{when}</b> {body}{src}")
        lines.append("<i>Apa adanya — kabar baik maupun buruk.</i>")
    else:
        lines += [
            "",
            f"<i>📰 Belum ada berita {result.ticker} di cache. Bukan berarti "
            f"tidak ada — sumber kami mungkin belum memuatnya.</i>",
        ]

    # Volume spikes are their own section now: where the unusual activity was,
    # independent of whether a headline happens to explain it.
    events = [e for e in (result.volume_events or [])][:3]
    if events:
        lines += ["", _DIV, "<b>Aktivitas volume</b>"]
        for ev in events:
            move = (
                f", harga {ev['change_percent']:+.2f}%"
                if ev.get("change_percent") is not None
                else ""
            )
            lines.append(
                f"📊 <b>{ev['date']}</b> — volume {ev['multiple']:.1f}x rata-rata{move}"
            )
            heads = ev.get("headlines") or []
            if heads:
                for h in heads[:2]:
                    src = f" <i>({h['source']})</i>" if h.get("source") else ""
                    lines.append(f"   ↳ bertepatan dengan: {h['title']}{src}")
            else:
                lines.append("   ↳ <i>tidak ada berita emiten terdeteksi hari itu</i>")
        lines.append(
            "<i>Berita di tanggal yang sama = kebetulan waktu, belum tentu penyebab.</i>"
        )

    if result.warnings:
        lines += ["", _DIV, "⚠️ <b>Catatan penting</b>"]
        lines += [f"• {w}" for w in result.warnings]

    lines += ["", f"<i>{result.disclaimer}</i>"]
    return "\n".join(lines)
