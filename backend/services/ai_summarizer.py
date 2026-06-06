"""
AI summarisation service using Anthropic tool-use for structured output.
Returns {summary, importance, impact} per news item in Bahasa Indonesia.

Cache is now persistent: SQLite via db.repository. Server restart != lost cache.
"""

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from db.repository import get_cached_summary, save_summary
from models.news import News

logger = logging.getLogger(__name__)

_client: Optional[AsyncAnthropic] = None

_SUMMARISE_TOOL = {
    "name": "summarise_news",
    "description": (
        "Produce a structured Bahasa Indonesia summary of a financial news item "
        "for Indonesian retail investors."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 2,
                "maxItems": 3,
                "description": (
                    "2-3 bullet ringkas dalam Bahasa Indonesia (≤20 kata per bullet), "
                    "bahasa lugas untuk investor ritel. Fokus: apa yang terjadi, "
                    "fakta kunci, dan konteks pasar."
                ),
            },
            "importance": {
                "type": "string",
                "enum": ["high", "medium", "low"],
                "description": (
                    "Tingkat urgensi berita untuk investor ritel. "
                    "HIGH = corporate action material (akuisisi/merger/rights issue/buyback), "
                    "earnings besar (rilis laporan keuangan emiten besar / kejutan laba-rugi), "
                    "atau perubahan regulasi yang mengubah aturan main pasar. "
                    "MEDIUM = berita signifikan tapi tidak mendesak (kerja sama bisnis, "
                    "perubahan manajemen menengah, tren sektoral). "
                    "LOW = berita rutin/umum (laporan harian indeks, opini, profil emiten, "
                    "berita makro yang sudah well-known)."
                ),
            },
            "impact": {
                "type": "string",
                "description": (
                    "Tepat 1 kalimat Bahasa Indonesia yang menjelaskan dampak konkret "
                    "berita ini bagi investor — misal arah harga saham, "
                    "implikasi terhadap valuasi, atau aksi yang relevan dipertimbangkan."
                ),
            },
        },
        "required": ["summary", "importance", "impact"],
    },
}

_SYSTEM_PROMPT = (
    "Kamu adalah analis keuangan yang merangkum berita pasar modal Indonesia "
    "untuk investor ritel. Gunakan Bahasa Indonesia yang ringkas, lugas, dan "
    "plain language (hindari jargon berat). Fokus pada fakta, dampak harga, "
    "dan relevansi bagi pemegang saham. Nilai importance secara jujur — "
    "jangan inflate semua berita menjadi 'high'."
)

_MODEL = "claude-haiku-4-5-20251001"

_EMPTY_RESULT: Dict[str, Any] = {
    "summary": [],
    "importance": "medium",
    "impact": None,
}


def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set in environment")
        _client = AsyncAnthropic(api_key=api_key)
    return _client


async def _call_claude(item: News) -> Dict[str, Any]:
    """Single Claude tool-use call. Returns _EMPTY_RESULT on any failure."""
    user_msg = (
        f"Judul: {item.title}\n"
        f"Sumber: {item.source.value}\n"
        f"Kutipan: {item.excerpt}"
    )
    try:
        client = _get_client()
        response = await client.messages.create(
            model=_MODEL,
            max_tokens=512,
            system=_SYSTEM_PROMPT,
            tools=[_SUMMARISE_TOOL],
            tool_choice={"type": "tool", "name": "summarise_news"},
            messages=[{"role": "user", "content": user_msg}],
        )
        tool_block = next(
            (b for b in response.content if b.type == "tool_use"), None
        )
        if tool_block is None:
            logger.warning("ai.no_tool_block news_id=%s", item.id)
            return dict(_EMPTY_RESULT)

        payload = tool_block.input or {}
        return {
            "summary": payload.get("summary", []) or [],
            "importance": payload.get("importance", "medium") or "medium",
            "impact": payload.get("impact"),
        }
    except Exception as exc:
        logger.error("ai.call_failed news_id=%s error=%s", item.id, exc)
        return dict(_EMPTY_RESULT)


async def summarize_and_persist(
    session: AsyncSession, item: News
) -> Dict[str, Any]:
    """
    Check DB cache → return cached if present.
    Otherwise call Claude, persist result, return it.
    """
    cached = await get_cached_summary(session, item.id)
    if cached is not None:
        return cached

    result = await _call_claude(item)
    # Persist even empty results to avoid retrying broken items every cycle
    await save_summary(
        session=session,
        news_id=item.id,
        summary=result["summary"],
        importance=result["importance"],
        impact=result["impact"],
    )
    return result


async def summarize_batch(
    session: AsyncSession, items: List[News], concurrency: int = 5
) -> Dict[str, int]:
    """
    Summarise a batch of items in parallel (bounded concurrency).
    Returns counts: {summarised, skipped, errors}.
    """
    if not items:
        return {"summarised": 0, "skipped": 0, "errors": 0}

    sem = asyncio.Semaphore(concurrency)
    stats = {"summarised": 0, "skipped": 0, "errors": 0}

    async def _one(item: News) -> None:
        async with sem:
            try:
                cached = await get_cached_summary(session, item.id)
                if cached is not None:
                    stats["skipped"] += 1
                    return
                result = await _call_claude(item)
                await save_summary(
                    session=session,
                    news_id=item.id,
                    summary=result["summary"],
                    importance=result["importance"],
                    impact=result["impact"],
                )
                if result["summary"]:
                    stats["summarised"] += 1
                else:
                    stats["errors"] += 1
            except Exception as exc:
                logger.error("ai.batch_item_failed news_id=%s error=%s", item.id, exc)
                stats["errors"] += 1

    await asyncio.gather(*(_one(n) for n in items))
    logger.info(
        "ai.batch_complete total=%d summarised=%d skipped=%d errors=%d",
        len(items), stats["summarised"], stats["skipped"], stats["errors"],
    )
    return stats
