"""
SQLAlchemy ORM tables for cached news + AI summaries.

`NewsRow` and `AISummaryRow` are separate tables so summary regeneration
doesn't touch the news row (and vice versa). One-to-one by news_id.
"""

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


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
