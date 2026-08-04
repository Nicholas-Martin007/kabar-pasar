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

    lines += [
        "",
        "<b>Skenario (asumsi posisi BELI)</b>",
        f"🎯 TP1: <b>{format_price(result.tp1, cur)}</b>  (1:{result.risk_reward_tp1:g})",
        f"🎯 TP2: <b>{format_price(result.tp2, cur)}</b>  (1:{result.risk_reward_tp2:g})",
        f"🛑 SL: <b>{format_price(result.sl, cur)}</b>",
        f"Risiko per lembar: {format_price(result.risk_per_share, cur)} {cur} "
        f"({result.risk_per_share / result.last_close:.1%} dari harga)",
    ]

    if result.warnings:
        lines += ["", "⚠️ <b>Catatan penting</b>"]
        lines += [f"• {w}" for w in result.warnings]

    lines += ["", f"<i>{result.disclaimer}</i>"]
    return "\n".join(lines)
