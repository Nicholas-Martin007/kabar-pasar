"""
Paper trading engine — SIMULATED ONLY.

Nothing here touches a real broker, a real account or real money. It exists so
someone can practise position sizing, stops and holding discipline from
Telegram while at work, with IDX's actual mechanics applied: 100-share lots,
tick-size validation, round-trip fees, auto-rejection bands and session hours.

The friction is the feature. A simulator without fees makes scalping look
profitable, teaches overtrading, and the habit transfers to a real account
where it costs money. At the default rates a position must move ~0.40% just to
break even — see `idx_rules.breakeven_price`.

Identity is the Telegram chat_id: no login, no password, and an account is
reachable only from the chat that owns it.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import PaperAccount, PaperOrder, PaperPosition
from backend.services.idx_rules import (
    LOT_SIZE,
    STARTING_CASH,
    breakeven_price,
    buy_cost,
    market_phase,
    sell_proceeds,
    within_auto_reject,
)
from ta_engine.price_utils import (
    idx_tick_size,
    is_idx_symbol,
    resolve_symbol,
)

logger = logging.getLogger(__name__)

# Stop-loss, take-profit and trailing stops all protect the SAME lots and
# only one of them can ever fire, so they are treated as an OCO group:
# they do not reserve lots against each other, and the survivors are
# cancelled or resized whenever the holding changes.
_PROTECTIVE = ("sl", "tp", "trail")

MAX_OPEN_ORDERS = 40


@dataclass
class OrderResult:
    ok: bool
    message: str
    order_id: Optional[int] = None
    filled: bool = False


async def get_or_create_account(session: AsyncSession, chat_id: str) -> PaperAccount:
    acct = await session.get(PaperAccount, chat_id)
    if acct is None:
        acct = PaperAccount(chat_id=chat_id, cash=STARTING_CASH)
        session.add(acct)
        await session.commit()
        logger.info("paper.account_created chat=%s cash=%.0f", chat_id, STARTING_CASH)
    return acct


async def _position(
    session: AsyncSession, chat_id: str, ticker: str
) -> Optional[PaperPosition]:
    return (
        await session.execute(
            select(PaperPosition).where(
                PaperPosition.chat_id == chat_id, PaperPosition.ticker == ticker
            )
        )
    ).scalars().first()


def _validate(ticker: str, price: Optional[float], lots: int) -> Optional[str]:
    """Reject anything the exchange itself would reject. Returns an error or None."""
    if lots <= 0:
        return "Jumlah lot harus lebih dari 0."
    if price is not None:
        if price <= 0:
            return "Harga harus lebih dari 0."
        if is_idx_symbol(ticker):
            tick = idx_tick_size(price)
            if price % tick != 0:
                return (
                    f"Harga {price:,.0f} tidak valid. Di rentang ini fraksi harga "
                    f"Rp{tick}, jadi harga harus kelipatan {tick} "
                    f"(mis. {int(price // tick) * tick:,} atau "
                    f"{int(price // tick + 1) * tick:,})."
                )
    return None


async def place_order(
    session: AsyncSession,
    chat_id: str,
    raw_ticker: str,
    side: str,
    lots: int,
    price: Optional[float] = None,
    kind: str = "limit",
    trail_pct: Optional[float] = None,
    last_price: Optional[float] = None,
    prev_close: Optional[float] = None,
) -> OrderResult:
    """
    Queue a simulated order, validating it the way the exchange would.

    A limit order priced at or through the market fills immediately; otherwise
    it rests until the price poller touches it. Orders placed outside session
    hours are accepted and queued rather than rejected, which mirrors real
    pre-market entry.
    """
    ticker = resolve_symbol(raw_ticker)
    acct = await get_or_create_account(session, chat_id)

    err = _validate(ticker, price, lots)
    if err:
        return OrderResult(False, f"⚠️ {err}")

    # Auto-rejection: a limit outside the daily band could never be entered.
    if price is not None and prev_close:
        if not within_auto_reject(price, prev_close):
            from backend.services.idx_rules import ara_arb_limits

            lo, hi = ara_arb_limits(prev_close)
            return OrderResult(
                False,
                f"⚠️ Harga {price:,.0f} kena auto-reject. Batas hari ini "
                f"{lo:,.0f}–{hi:,.0f} (dari close {prev_close:,.0f}).",
            )

    open_count = (
        await session.execute(
            select(PaperOrder).where(
                PaperOrder.chat_id == chat_id, PaperOrder.status == "open"
            )
        )
    ).scalars().all()
    if len(open_count) >= MAX_OPEN_ORDERS:
        return OrderResult(False, f"⚠️ Terlalu banyak order terbuka (maks {MAX_OPEN_ORDERS}).")

    if side == "sell":
        pos = await _position(session, chat_id, ticker)
        held = pos.lots if pos else 0
        same = [o for o in open_count if o.ticker == ticker and o.side == "sell"]

        if kind in _PROTECTIVE:
            # Capped at the holding, but NOT against sibling exits — otherwise
            # setting a stop loss would make a take-profit impossible, which is
            # the pairing almost every trader actually wants.
            if held < lots:
                return OrderResult(
                    False,
                    f"⚠️ Lot tidak cukup. Punya {held} lot, mau pasang {lots}.",
                )
            # Placing the same kind again means "move it", not "add another".
            for o in same:
                if o.kind == kind:
                    o.status = "cancelled"
                    o.reason = "replaced"
        else:
            # Manual sells DO reserve, so two of them can't promise the same
            # shares. Protective exits are excluded from the reservation.
            pending = sum(o.lots for o in same if o.kind not in _PROTECTIVE)
            if held - pending < lots:
                return OrderResult(
                    False,
                    f"⚠️ Lot tidak cukup. Punya {held} lot"
                    + (f", {pending} sudah dipesan untuk dijual" if pending else "")
                    + f", mau jual {lots}.",
                )

    order = PaperOrder(
        chat_id=chat_id, ticker=ticker, side=side, kind=kind,
        limit_price=price, lots=lots, trail_pct=trail_pct,
        peak_price=last_price if kind == "trail" else None,
        status="open",
    )
    session.add(order)
    await session.commit()

    # Immediate fill when a limit is already marketable.
    if kind == "limit" and last_price is not None and price is not None:
        marketable = (side == "buy" and last_price <= price) or (
            side == "sell" and last_price >= price
        )
        if marketable:
            filled = await _fill(session, order, last_price)
            if filled.ok:
                return filled

    phase = market_phase()
    note = "" if phase == "open" else f" (pasar {phase} — order antre)"
    verb = "Beli" if side == "buy" else "Jual"
    if kind == "trail":
        px = f"trailing {trail_pct:g}%"
    elif price:
        px = f"@ {price:,.0f}"
    else:
        px = ""
    label = {"sl": " — stop loss", "tp": " — take profit",
             "trail": " — trailing stop"}.get(kind, "")
    return OrderResult(
        True,
        f"✅ Order #{order.id} tercatat{label}: {verb} "
        f"<b>{ticker.replace('.JK','')}</b> {lots} lot {px}{note}.",
        order_id=order.id,
    )


async def _reconcile_exits(
    session: AsyncSession, chat_id: str, ticker: str
) -> List[int]:
    """
    OCO cleanup after a fill: cancel or shrink exits that outlive their lots.

    Protective exits all cover the same holding, so once one fires the others
    are stale. Without this a stop loss left over from a closed position would
    later "fill" against shares the user no longer owns.

    Returns the ids of orders that were cancelled.
    """
    pos = await _position(session, chat_id, ticker)
    held = pos.lots if pos else 0
    rows = (
        await session.execute(
            select(PaperOrder).where(
                PaperOrder.chat_id == chat_id,
                PaperOrder.ticker == ticker,
                PaperOrder.side == "sell",
                PaperOrder.status == "open",
            )
        )
    ).scalars().all()

    cancelled: List[int] = []
    for o in rows:
        if held <= 0:
            o.status = "cancelled"
            o.reason = "position closed"
            cancelled.append(o.id)
        elif o.lots > held:
            o.lots = held
    return cancelled


async def _fill(
    session: AsyncSession, order: PaperOrder, price: float
) -> OrderResult:
    """Execute a resting order at `price`, updating cash and position."""
    acct = await get_or_create_account(session, order.chat_id)
    pos = await _position(session, order.chat_id, order.ticker)
    short_name = order.ticker.replace(".JK", "")

    if order.side == "buy":
        cost = buy_cost(price, order.lots)
        if cost.net > acct.cash:
            order.status = "rejected"
            order.reason = "insufficient cash"
            await session.commit()
            return OrderResult(
                False,
                f"❌ Order #{order.id} ditolak: butuh Rp{cost.net:,.0f}, "
                f"saldo Rp{acct.cash:,.0f}.",
            )
        acct.cash -= cost.net
        acct.fees_paid += cost.fee
        # Average in the fee so the position knows its true cost basis.
        eff = cost.net / (order.lots * LOT_SIZE)
        if pos is None:
            session.add(PaperPosition(
                chat_id=order.chat_id, ticker=order.ticker,
                lots=order.lots, avg_price=eff,
            ))
        else:
            total = pos.lots + order.lots
            pos.avg_price = (pos.avg_price * pos.lots + eff * order.lots) / total
            pos.lots = total
        msg = (
            f"🟢 <b>FILLED</b> #{order.id} — Beli {short_name} {order.lots} lot "
            f"@ {price:,.0f}\n"
            f"Biaya Rp{cost.fee:,.0f} · Total Rp{cost.net:,.0f}\n"
            f"Sisa saldo Rp{acct.cash:,.0f}"
        )
    else:
        if pos is None or pos.lots < order.lots:
            order.status = "rejected"
            order.reason = "position gone"
            await session.commit()
            return OrderResult(False, f"❌ Order #{order.id} ditolak: posisi tidak ada.")
        proceeds = sell_proceeds(price, order.lots)
        cost_basis = pos.avg_price * order.lots * LOT_SIZE
        pnl = proceeds.net - cost_basis
        acct.cash += proceeds.net
        acct.fees_paid += proceeds.fee
        acct.realised += pnl
        pos.lots -= order.lots
        if pos.lots <= 0:
            await session.delete(pos)
        emoji = "🟩" if pnl >= 0 else "🟥"
        msg = (
            f"🔴 <b>FILLED</b> #{order.id} — Jual {short_name} {order.lots} lot "
            f"@ {price:,.0f}\n"
            f"Biaya Rp{proceeds.fee:,.0f} · Terima Rp{proceeds.net:,.0f}\n"
            f"{emoji} P&amp;L Rp{pnl:,.0f} ({pnl / cost_basis * 100:+.2f}%)\n"
            f"Saldo Rp{acct.cash:,.0f}"
        )

    order.status = "filled"
    order.fill_price = price
    order.filled_at = datetime.now(timezone.utc)
    # Marked filled first, so the order does not cancel itself here.
    cancelled = await _reconcile_exits(session, order.chat_id, order.ticker)
    if cancelled:
        ids = ", ".join(f"#{i}" for i in cancelled)
        msg += f"\n<i>Order proteksi {ids} otomatis dibatalkan (OCO).</i>"
    await session.commit()
    logger.info(
        "paper.filled chat=%s order=%d %s %s %d lots @ %.0f",
        order.chat_id, order.id, order.side, order.ticker, order.lots, price,
    )
    return OrderResult(True, msg, order_id=order.id, filled=True)


async def match_open_orders(
    session: AsyncSession, prices: Dict[str, float]
) -> List[Tuple[str, str]]:
    """
    Check every resting order against current prices.

    Returns (chat_id, message) for each fill so the caller can notify. Prices
    are supplied by the caller (the scheduler's matcher job) rather than fetched
    here, so one quote sweep serves the whole matching pass.
    """
    orders = (
        await session.execute(
            select(PaperOrder).where(PaperOrder.status == "open")
        )
    ).scalars().all()

    out: List[Tuple[str, str]] = []
    for o in orders:
        px = prices.get(o.ticker)
        if px is None:
            continue

        hit = False
        if o.kind == "limit":
            hit = (o.side == "buy" and px <= (o.limit_price or 0)) or (
                o.side == "sell" and px >= (o.limit_price or 0)
            )
        elif o.kind == "sl":
            hit = px <= (o.limit_price or 0)
        elif o.kind == "tp":
            hit = px >= (o.limit_price or 0)
        elif o.kind == "trail" and o.trail_pct:
            # Ratchet the peak up, never down; trigger when price falls back
            # through the trailing distance from that peak.
            peak = max(o.peak_price or px, px)
            if peak != o.peak_price:
                o.peak_price = peak
            stop = peak * (1 - o.trail_pct / 100)
            hit = px <= stop

        if hit:
            res = await _fill(session, o, px)
            out.append((o.chat_id, res.message))

    await session.commit()
    return out


async def portfolio(
    session: AsyncSession, chat_id: str, prices: Dict[str, float]
) -> Dict[str, Any]:
    """Account snapshot with unrealised P&L marked to `prices`."""
    acct = await get_or_create_account(session, chat_id)
    positions = (
        await session.execute(
            select(PaperPosition).where(PaperPosition.chat_id == chat_id)
        )
    ).scalars().all()

    rows, market_value, unrealised = [], 0.0, 0.0
    for p in positions:
        px = prices.get(p.ticker)
        shares = p.lots * LOT_SIZE
        basis = p.avg_price * shares
        value = (px * shares) if px else basis
        pnl = value - basis
        market_value += value
        unrealised += pnl
        rows.append({
            "ticker": p.ticker.replace(".JK", ""),
            "lots": p.lots,
            "avg_price": p.avg_price,
            "last": px,
            "value": value,
            "pnl": pnl,
            "pnl_pct": (pnl / basis * 100) if basis else 0.0,
            "breakeven": breakeven_price(p.avg_price),
        })

    rows.sort(key=lambda r: -abs(r["pnl"]))
    equity = acct.cash + market_value
    return {
        "cash": acct.cash,
        "market_value": market_value,
        "equity": equity,
        "unrealised": unrealised,
        "realised": acct.realised,
        "fees_paid": acct.fees_paid,
        "starting": STARTING_CASH,
        "total_return_pct": (equity - STARTING_CASH) / STARTING_CASH * 100,
        "positions": rows,
    }


async def reset_account(session: AsyncSession, chat_id: str) -> None:
    """Wipe positions and orders, restore the starting balance."""
    for model in (PaperPosition, PaperOrder):
        for row in (
            await session.execute(select(model).where(model.chat_id == chat_id))
        ).scalars().all():
            await session.delete(row)
    acct = await get_or_create_account(session, chat_id)
    acct.cash = STARTING_CASH
    acct.realised = 0.0
    acct.fees_paid = 0.0
    await session.commit()
    logger.info("paper.account_reset chat=%s", chat_id)


async def position_lots(session: AsyncSession, chat_id: str, ticker: str) -> int:
    pos = await _position(session, chat_id, ticker)
    return pos.lots if pos else 0


async def list_open_orders(session: AsyncSession, chat_id: str) -> List[Dict[str, Any]]:
    rows = (
        await session.execute(
            select(PaperOrder)
            .where(PaperOrder.chat_id == chat_id, PaperOrder.status == "open")
            .order_by(PaperOrder.id)
        )
    ).scalars().all()
    return [
        {
            "id": o.id, "ticker": o.ticker.replace(".JK", ""), "side": o.side,
            "kind": o.kind, "limit_price": o.limit_price, "lots": o.lots,
            "trail_pct": o.trail_pct,
        }
        for o in rows
    ]


async def cancel_order(session: AsyncSession, chat_id: str, order_id: int) -> bool:
    o = await session.get(PaperOrder, order_id)
    # Scoped to the owning chat: an order id is a small sequential integer and
    # trivially guessable, so without this check one user could cancel another's
    # order just by trying numbers.
    if o is None or o.chat_id != chat_id or o.status != "open":
        return False
    o.status = "cancelled"
    await session.commit()
    return True


async def open_order_tickers(session: AsyncSession) -> List[str]:
    """Distinct tickers with at least one resting order — the matcher's quote set."""
    rows = (
        await session.execute(
            select(PaperOrder.ticker).where(PaperOrder.status == "open").distinct()
        )
    ).scalars().all()
    return list(rows)
