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

from typing import TYPE_CHECKING, List

from .price_utils import format_price

if TYPE_CHECKING:  # avoid a circular import at runtime
    from .chart_generator import ChartResult

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
        f"• ATR(14) {format_price(result.atr, cur)} — ukuran volatilitas harian",
        "",
        "<b>Level kunci</b>",
    ]

    # Mirror the chart's sentiment badge. Without this the image says
    # "WARNING / BEARISH" while the caption beside it says nothing, and the
    # reader has to reconcile the two.
    if result.pattern_detected and result.pattern_name:
        icon = {"BULLISH": "🟢", "BEARISH_WARNING": "🔴"}.get(result.sentiment, "🟡")
        tf = result.selected_timeframe.upper()
        lines += [
            "",
            f"{icon} <b>Pola terdeteksi:</b> {result.pattern_name} "
            f"({tf}, kemiripan bentuk {result.quality_score * 100:.0f}%)",
            "<i>Skor = seberapa rapi bentuknya, bukan peluang berhasil.</i>",
        ]

    if result.support is not None:
        lines.append(f"🟢 Support: <b>{format_price(result.support, cur)}</b>")
    else:
        lines.append("🟢 Support: <i>tidak terdeteksi di bawah harga</i>")
    if result.resistance is not None:
        lines.append(f"🔴 Resistance: <b>{format_price(result.resistance, cur)}</b>")
    else:
        lines.append("🔴 Resistance: <i>tidak terdeteksi di atas harga</i>")

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
        lines += ["", "<b>Rencana masuk</b>", f"🟩 Ideal beli di {zone}"]

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

    if result.pattern_target is not None and result.pattern_breakout is not None:
        lines += [
            "",
            f"📐 Measured move pola: tembus <b>{format_price(result.pattern_breakout, cur)}</b> "
            f"→ proyeksi <b>{format_price(result.pattern_target, cur)}</b>",
        ]

    # Valuation, so the reader sees whether the chart is attached to a business
    # that earns money. Metrics that failed validation are simply absent — see
    # ta_engine.fundamentals on why bad vendor data is dropped, not shown.
    if result.fundamentals_summary:
        lines += ["", "<b>Fundamental</b>", f"🏦 {result.fundamentals_summary}"]
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
        lines += ["", f"<b>Berita terbaru {result.ticker}</b>"]
        for n in news[:5]:
            dot = icon.get(n.get("importance"), "⚪")
            when = str(n.get("publishedAt") or "")[:10]
            flag = "🚨 " if n.get("isMsciAlert") else ""
            title = n.get("title") or ""
            lines.append(f"{dot} {flag}<b>{when}</b> {title}")
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
        lines += ["", "<b>Aktivitas volume &amp; berita</b>"]
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
        lines += ["", "⚠️ <b>Catatan penting</b>"]
        lines += [f"• {w}" for w in result.warnings]

    lines += ["", f"<i>{result.disclaimer}</i>"]
    return "\n".join(lines)
