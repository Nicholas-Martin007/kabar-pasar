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
