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
        f"Harga terakhir: <b>{result.last_close:,.2f} {cur}</b>",
        f"• {_trend_phrase(result.last_close, result.ema20, result.ema50)}",
        f"• {_rsi_phrase(result.rsi)}",
        f"• ATR(14) {result.atr:,.2f} — ukuran volatilitas harian",
        "",
        "<b>Level kunci</b>",
    ]

    if result.support is not None:
        lines.append(f"🟢 Support: <b>{result.support:,.2f}</b>")
    else:
        lines.append("🟢 Support: <i>tidak terdeteksi di bawah harga</i>")
    if result.resistance is not None:
        lines.append(f"🔴 Resistance: <b>{result.resistance:,.2f}</b>")
    else:
        lines.append("🔴 Resistance: <i>tidak terdeteksi di atas harga</i>")

    lines += [
        "",
        "<b>Skenario (asumsi posisi BELI)</b>",
        f"🎯 TP1: <b>{result.tp1:,.2f}</b>  (1:{result.risk_reward_tp1:g})",
        f"🎯 TP2: <b>{result.tp2:,.2f}</b>  (1:{result.risk_reward_tp2:g})",
        f"🛑 SL: <b>{result.sl:,.2f}</b>",
        f"Risiko per lembar: {result.risk_per_share:,.2f} {cur} "
        f"({result.risk_per_share / result.last_close:.1%} dari harga)",
    ]

    if result.warnings:
        lines += ["", "⚠️ <b>Catatan penting</b>"]
        lines += [f"• {w}" for w in result.warnings]

    lines += ["", f"<i>{result.disclaimer}</i>"]
    return "\n".join(lines)
