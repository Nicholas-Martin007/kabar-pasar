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


async def init_db() -> None:
    """Create tables if they don't exist. Idempotent — safe to call every startup."""
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
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
