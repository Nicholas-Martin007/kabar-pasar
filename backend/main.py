import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Dict

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from db.session import dispose as db_dispose
from db.session import init_db
from routers import market as market_router
from routers import news as news_router
from services.scheduler import refresh_news_job, shutdown_scheduler, start_scheduler
from services.telegram_service import poll_updates_loop

load_dotenv()

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


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health", tags=["meta"])
async def health() -> Dict[str, str]:
    return {"status": "ok", "service": "kabar-pasar-api"}


# ── Root ─────────────────────────────────────────────────────────────────────
@app.get("/", tags=["meta"])
async def root() -> Dict[str, str]:
    return {"message": "Kabar Pasar API", "docs": "/docs"}
