"""
AI summarisation service using Anthropic tool-use for structured output.
Returns 3 concise Bahasa Indonesia bullets per news item.
Results are cached in-memory by item id to avoid redundant API calls.
"""

import asyncio
import json
import logging
import os
from typing import Dict, List, Optional

from anthropic import AsyncAnthropic

from models.news import News

logger = logging.getLogger(__name__)

_client: Optional[AsyncAnthropic] = None

# id → List[str] (3 bullets)
_cache: Dict[str, List[str]] = {}

_SUMMARISE_TOOL = {
    "name": "summarise_news",
    "description": (
        "Produce a structured summary of a financial news item for retail investors."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "bullets": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 3,
                "maxItems": 3,
                "description": (
                    "Exactly 3 concise Bahasa Indonesia bullets (≤20 words each). "
                    "Focus on: what happened, market impact, and investor implication."
                ),
            }
        },
        "required": ["bullets"],
    },
}

_SYSTEM_PROMPT = (
    "Kamu adalah analis keuangan yang merangkum berita pasar modal Indonesia "
    "untuk investor ritel. Gunakan Bahasa Indonesia yang ringkas dan lugas. "
    "Fokus pada fakta, dampak harga, dan relevansi bagi pemegang saham."
)

_MODEL = "claude-haiku-4-5-20251001"


def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set in environment")
        _client = AsyncAnthropic(api_key=api_key)
    return _client


async def _summarise_one(item: News) -> List[str]:
    """Call Claude with tool-use and return exactly 3 bullet strings."""
    if item.id in _cache:
        return _cache[item.id]

    user_msg = (
        f"Judul: {item.title}\n"
        f"Sumber: {item.source.value}\n"
        f"Kutipan: {item.excerpt}"
    )

    try:
        client = _get_client()
        response = await client.messages.create(
            model=_MODEL,
            max_tokens=256,
            system=_SYSTEM_PROMPT,
            tools=[_SUMMARISE_TOOL],
            tool_choice={"type": "tool", "name": "summarise_news"},
            messages=[{"role": "user", "content": user_msg}],
        )

        tool_block = next(
            (b for b in response.content if b.type == "tool_use"), None
        )
        if tool_block is None:
            logger.warning("No tool_use block for item %s", item.id)
            return []

        bullets: List[str] = tool_block.input.get("bullets", [])
        _cache[item.id] = bullets
        return bullets

    except Exception as exc:
        logger.error("AI summarise failed for item %s: %s", item.id, exc)
        return []


async def enrich_with_summaries(items: List[News], limit: int = 10) -> List[News]:
    """
    Batch-summarise up to *limit* items concurrently.
    Items beyond *limit* are returned with their existing ai_summary unchanged.
    """
    to_summarise = items[:limit]
    rest = items[limit:]

    summaries = await asyncio.gather(
        *(_summarise_one(n) for n in to_summarise), return_exceptions=True
    )

    enriched: List[News] = []
    for item, result in zip(to_summarise, summaries):
        if isinstance(result, list) and result:
            enriched.append(item.model_copy(update={"ai_summary": result}))
        else:
            enriched.append(item)

    return enriched + rest
