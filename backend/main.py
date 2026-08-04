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

from backend.db.repository import backfill_msci_flags  # noqa: E402
from backend.db.session import dispose as db_dispose  # noqa: E402
from backend.db.session import get_session  # noqa: E402
from backend.db.session import init_db  # noqa: E402
from backend.routers import market as market_router  # noqa: E402
from backend.routers import news as news_router  # noqa: E402
from backend.routers import telegram as telegram_router  # noqa: E402
from backend.services.scheduler import (  # noqa: E402
    refresh_news_job,
    shutdown_scheduler,
    start_scheduler,
)
from backend.routers import charts as charts_router  # noqa: E402
from backend.routers import ihsg as ihsg_router  # noqa: E402
from backend.tasks import pool as task_pool  # noqa: E402
from backend.routers import commodities as commodities_router  # noqa: E402
from backend.routers import stream as stream_router  # noqa: E402
from scrapers.commodity_tracker import poll_loop as commodity_poll_loop  # noqa: E402
from scrapers.news_scraper import poll_loop as news_poll_loop  # noqa: E402
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
    # Classify news cached before the MSCI columns existed. Only matching rows
    # are written, so this is effectively a no-op after the first run.
    try:
        async with get_session() as session:
            await backfill_msci_flags(session)
    except Exception as exc:
        logger.warning("app.msci_backfill_failed error=%s", exc)
    # Worker pool first: the scheduler and pollers below hand work to it, and a
    # job submitted before the workers exist would sit in the queue unclaimed.
    task_pool.start()
    start_scheduler()
    # Kick off an initial refresh in the background — don't block server startup
    asyncio.create_task(_initial_refresh())

    # Long-running pollers. All are cancelled on shutdown; each is individually
    # disable-able by env so one misbehaving source can be turned off without
    # taking the API down.
    background = [
        asyncio.create_task(poll_updates_loop(), name="telegram"),
        asyncio.create_task(news_poll_loop(), name="news_fastpoll"),
        asyncio.create_task(commodity_poll_loop(), name="commodity"),
    ]
    logger.info("app.startup_complete background_tasks=%d", len(background))
    try:
        yield
    finally:
        # Shutdown
        for task in background:
            task.cancel()
        # Let each task observe the cancellation and run its finally blocks.
        await asyncio.gather(*background, return_exceptions=True)
        shutdown_scheduler()
        await task_pool.stop()
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
app.include_router(commodities_router.router)
app.include_router(stream_router.router)
app.include_router(charts_router.router)
app.include_router(ihsg_router.router)


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health", tags=["meta"])
async def health() -> Dict[str, str]:
    return {"status": "ok", "service": "kabar-pasar-api"}


# ── Root ─────────────────────────────────────────────────────────────────────
@app.get("/", tags=["meta"])
async def root() -> Dict[str, str]:
    return {"message": "Kabar Pasar API", "docs": "/docs"}
