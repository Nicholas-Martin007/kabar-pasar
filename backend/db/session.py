"""
Async engine + session factory.

DATABASE_URL examples:
  sqlite+aiosqlite:///./data/kabar_pasar.db   (default — local dev)
  postgresql+asyncpg://user:pw@host/db        (production swap)
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .models import Base

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "kabar_pasar.db"
_DEFAULT_URL = f"sqlite+aiosqlite:///{_DEFAULT_DB_PATH.as_posix()}"

DATABASE_URL = os.getenv("DATABASE_URL") or _DEFAULT_URL

# SQLite needs the directory to exist before connecting
if DATABASE_URL.startswith("sqlite"):
    _DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

_engine = create_async_engine(DATABASE_URL, echo=False, future=True)
_SessionFactory = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)


_MIGRATIONS = [
    # Columns added to telegram_subscriber over time. ALTER fails if the column
    # already exists — caught and ignored, so this is safe every startup.
    "ALTER TABLE telegram_subscriber ADD COLUMN keywords JSON",
    "ALTER TABLE telegram_subscriber ADD COLUMN mute JSON",
    "ALTER TABLE telegram_subscriber ADD COLUMN all_news BOOLEAN DEFAULT 0",
    "ALTER TABLE telegram_subscriber ADD COLUMN high_only BOOLEAN DEFAULT 0",
    "ALTER TABLE telegram_subscriber ADD COLUMN link_token VARCHAR(64)",
    # Control-panel filters. Defaults chosen so existing subscribers are
    # unaffected: news stays on, stockpicks stay off, empty sources means "all",
    # and min_rsi=100 excludes nothing.
    "ALTER TABLE telegram_subscriber ADD COLUMN news_alerts BOOLEAN DEFAULT 1",
    "ALTER TABLE telegram_subscriber ADD COLUMN stockpick_alerts BOOLEAN DEFAULT 0",
    "ALTER TABLE telegram_subscriber ADD COLUMN sources JSON",
    "ALTER TABLE telegram_subscriber ADD COLUMN min_rsi INTEGER DEFAULT 100",
    # MSCI priority routing. Existing rows default to not-an-MSCI-alert at
    # NORMAL priority, so back-filling changes nothing for cached news.
    "ALTER TABLE news ADD COLUMN is_msci_alert BOOLEAN DEFAULT 0",
    "ALTER TABLE news ADD COLUMN priority VARCHAR(16) DEFAULT 'NORMAL'",
]


async def init_db() -> None:
    """Create tables if missing + apply additive column migrations. Idempotent."""
    from sqlalchemy import text

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for stmt in _MIGRATIONS:
            try:
                await conn.execute(text(stmt))
            except Exception:
                pass  # column already exists — fine
    logger.info("db.initialised url=%s", DATABASE_URL.split("://", 1)[0])


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Async session context manager. Caller is responsible for commit/rollback."""
    async with _SessionFactory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def dispose() -> None:
    """Close engine connections — call on shutdown."""
    await _engine.dispose()
