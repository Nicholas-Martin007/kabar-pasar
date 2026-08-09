"""
SQLAlchemy ORM tables for cached news + AI summaries.

`NewsRow` and `AISummaryRow` are separate tables so summary regeneration
doesn't touch the news row (and vice versa). One-to-one by news_id.
"""

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import DateTime, Float, ForeignKey, Index, JSON, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class NewsRow(Base):
    __tablename__ = "news"

    id:            Mapped[str]      = mapped_column(String(32), primary_key=True)
    title:         Mapped[str]      = mapped_column(Text, nullable=False)
    source:        Mapped[str]      = mapped_column(String(64), nullable=False, index=True)
    published_at:  Mapped[str]      = mapped_column(String(32), nullable=False, index=True)
    excerpt:       Mapped[str]      = mapped_column(Text, default="")
    tickers:       Mapped[List[str]] = mapped_column(JSON, default=list)
    importance:    Mapped[str]      = mapped_column(String(16), default="medium", index=True)
    category:      Mapped[str]      = mapped_column(String(32), default="market_news")
    url:           Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ── MSCI priority routing ────────────────────────────────────────────────
    # MSCI index reviews force mechanical index-fund flows through IDX names, so
    # they get their own alert class instead of competing with ordinary news.
    # Indexed because the alert path filters on it every cycle.
    is_msci_alert: Mapped[bool] = mapped_column(default=False, index=True)
    # "HIGH" | "NORMAL". Separate from `importance` on purpose: importance is a
    # content judgement, priority is a routing decision.
    priority:      Mapped[str]  = mapped_column(String(16), default="NORMAL", index=True)

    created_at:    Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at:    Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    ai_summary:    Mapped[Optional["AISummaryRow"]] = relationship(
        back_populates="news", uselist=False, cascade="all, delete-orphan"
    )


class TelegramSubscriber(Base):
    """A Telegram chat subscribed to watchlist news alerts."""

    __tablename__ = "telegram_subscriber"

    chat_id:    Mapped[str]      = mapped_column(String(32), primary_key=True)
    tickers:    Mapped[List[str]] = mapped_column(JSON, default=list)
    # Free-text topics/sources to follow (lowercase), e.g. "emas", "bloomberg".
    keywords:   Mapped[List[str]] = mapped_column(JSON, default=list)
    # Topics/sources to silence while in firehose mode (lowercase).
    mute:       Mapped[List[str]] = mapped_column(JSON, default=list)
    # Firehose: receive every news item (default ON for new /start subscribers).
    all_news:   Mapped[bool]      = mapped_column(default=False)
    # Only deliver HIGH-importance news (applied on top of the other filters).
    high_only:  Mapped[bool]      = mapped_column(default=False)
    # Persistent token the linked app uses to push watchlist updates.
    link_token: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)

    # ── Control-panel filters (set from the app's Telegram settings screen) ──
    # Master switches per alert kind.
    news_alerts:      Mapped[bool] = mapped_column(default=True)
    stockpick_alerts: Mapped[bool] = mapped_column(default=False)
    # Allow-list of NewsSource values. EMPTY LIST MEANS "all sources" — not
    # "none" — so existing subscribers keep receiving everything after this
    # column is added.
    sources:          Mapped[List[str]] = mapped_column(JSON, default=list)
    # Screener threshold: only surface picks at/below this RSI (oversold hunting).
    min_rsi:          Mapped[int] = mapped_column(default=100)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class CommodityPriceRow(Base):
    """
    Timestamped commodity price history, one row per observed price change.

    The tracker only writes when the price actually moves, so an overnight
    market that is closed costs nothing instead of storing the same number
    every polling interval.

    `is_proxy` matters for correctness, not bookkeeping: Yahoo has no free
    futures contract for coal or nickel, so those entries are *equity proxies*
    (Indonesian miners) — a mining company's share price, not a commodity
    price. Anything rendering this table must surface that distinction rather
    than presenting a proxy as a spot price.
    """

    __tablename__ = "commodity_price"
    __table_args__ = (
        Index("ix_commodity_symbol_recorded", "symbol", "recorded_at"),
    )

    id:             Mapped[int]      = mapped_column(primary_key=True, autoincrement=True)
    symbol:         Mapped[str]      = mapped_column(String(32), nullable=False, index=True)
    name:           Mapped[str]      = mapped_column(String(64), nullable=False)
    price:          Mapped[float]    = mapped_column(Float, nullable=False)
    currency:       Mapped[str]      = mapped_column(String(8), default="USD")
    change:         Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    change_percent: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_proxy:       Mapped[bool]     = mapped_column(default=False)
    recorded_at:    Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)


class AISummaryRow(Base):
    __tablename__ = "ai_summary"

    news_id:       Mapped[str]      = mapped_column(
        String(32), ForeignKey("news.id", ondelete="CASCADE"), primary_key=True
    )
    summary:       Mapped[List[str]] = mapped_column(JSON, default=list)
    importance:    Mapped[str]      = mapped_column(String(16), default="medium")
    impact:        Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at:    Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    news:          Mapped["NewsRow"] = relationship(back_populates="ai_summary")


# ── Paper trading (simulated; no real money, no broker) ──────────────────────


class PaperAccount(Base):
    """
    A simulated trading account, keyed on Telegram chat_id.

    No login by design: the chat itself is the identity, which is the whole
    point of running this in Telegram. That also means an account is only ever
    reachable from the chat that owns it.
    """

    __tablename__ = "paper_account"

    chat_id:    Mapped[str]      = mapped_column(String(32), primary_key=True)
    cash:       Mapped[float]    = mapped_column(Float, nullable=False)
    # Realised P&L only; unrealised is computed live from current prices.
    realised:   Mapped[float]    = mapped_column(Float, default=0.0)
    fees_paid:  Mapped[float]    = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class PaperPosition(Base):
    """An open holding. `lots`, not shares — IDX trades in lots of 100."""

    __tablename__ = "paper_position"
    __table_args__ = (Index("ix_paper_pos_chat_ticker", "chat_id", "ticker"),)

    id:        Mapped[int]   = mapped_column(primary_key=True, autoincrement=True)
    chat_id:   Mapped[str]   = mapped_column(String(32), nullable=False, index=True)
    ticker:    Mapped[str]   = mapped_column(String(16), nullable=False)
    lots:      Mapped[int]   = mapped_column(default=0)
    # Weighted average INCLUDING buy fees, so P&L is honest about entry cost.
    avg_price: Mapped[float] = mapped_column(Float, nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class PaperOrder(Base):
    """
    A resting or completed simulated order.

    Stop-loss and take-profit are stored as orders rather than as fields on the
    position so a single holding can carry several exits at once, which is how
    people actually scale out.
    """

    __tablename__ = "paper_order"
    # Composite index for the matcher's "all open orders" sweep. Named distinctly
    # from the per-column index SQLAlchemy derives for `status` (index=True),
    # which would otherwise collide on ix_paper_order_status.
    __table_args__ = (Index("ix_paper_order_status_ticker", "status", "ticker"),)

    id:          Mapped[int]   = mapped_column(primary_key=True, autoincrement=True)
    chat_id:     Mapped[str]   = mapped_column(String(32), nullable=False, index=True)
    ticker:      Mapped[str]   = mapped_column(String(16), nullable=False)
    side:        Mapped[str]   = mapped_column(String(4))    # buy | sell
    # limit | sl (stop-loss) | tp (take-profit) | trail
    kind:        Mapped[str]   = mapped_column(String(8), default="limit")
    limit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lots:        Mapped[int]   = mapped_column(default=0)
    # open | filled | cancelled | rejected
    status:      Mapped[str]   = mapped_column(String(12), default="open", index=True)
    reason:      Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Trailing stops: distance in %, and the best price seen since placement.
    trail_pct:   Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    peak_price:  Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fill_price:  Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at:  Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    filled_at:   Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
