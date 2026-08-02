import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict

from dotenv import load_dotenv

# Must run BEFORE the project imports below: db.session reads DATABASE_URL at
# module scope, so a late load_dotenv() would silently ignore it. The absolute
# path also makes this CWD-independent — the app is now launched from the repo
# root (`uvicorn backend.main:app`), where a bare load_dotenv() would pick up
# the root .env (Expo vars) instead of backend/.env.
load_dotenv(Path(__file__).resolve().parent / ".env")

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from backend.db.session import dispose as db_dispose  # noqa: E402
from backend.db.session import init_db  # noqa: E402
from backend.routers import market as market_router  # noqa: E402
from backend.routers import news as news_router  # noqa: E402
from backend.routers import telegram as telegram_router  # noqa: E402
from backend.services.scheduler import (  # noqa: E402
    refresh_news_job,
    shutdown_scheduler,
    start_scheduler,
)
from telegram_bot.telegram_service import poll_updates_loop  # noqa: E402

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    start_scheduler()
    # Kick off an initial refresh in the background — don't block server startup
    asyncio.create_task(_initial_refresh())
    # Telegram command poller (no-op if TELEGRAM_BOT_TOKEN unset)
    telegram_task = asyncio.create_task(poll_updates_loop())
    logger.info("app.startup_complete")
    try:
        yield
    finally:
        # Shutdown
        telegram_task.cancel()
        shutdown_scheduler()
        await db_dispose()
        logger.info("app.shutdown_complete")


async def _initial_refresh() -> None:
    try:
        await refresh_news_job()
    except Exception as exc:
        logger.warning("app.initial_refresh_failed error=%s", exc)


app = FastAPI(
    title="Kabar Pasar API",
    description="Financial news aggregation backend for Kabar Pasar.",
    version="0.2.0",
    lifespan=lifespan,
)

# ── CORS ─────────────────────────────────────────────────────────────────────
_raw_origins = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:8081,http://localhost:19006,exp://localhost:8081",
)
_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(news_router.router)
app.include_router(market_router.router)
app.include_router(telegram_router.router)


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health", tags=["meta"])
async def health() -> Dict[str, str]:
    return {"status": "ok", "service": "kabar-pasar-api"}


# ── Root ─────────────────────────────────────────────────────────────────────
@app.get("/", tags=["meta"])
async def root() -> Dict[str, str]:
    return {"message": "Kabar Pasar API", "docs": "/docs"}
