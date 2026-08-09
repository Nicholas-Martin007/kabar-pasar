"""
Links price action to the news that plausibly caused it.

A candlestick chart tells you *that* volume tripled on 22 July. It cannot tell
you *why*, and "why" is the part a retail investor actually needs — it is the
difference between a one-off headline reaction and a change in the story.

This module finds unusual volume, then looks for news about that ticker on the
same day, and pairs them up.

## The honest framing: co-occurrence, not causation

A headline on the same day as a volume spike is **temporal coincidence**. It
does not prove the news moved the price, and on a busy day several unrelated
stories will share a date with any spike. So:

* Output is worded as "coincided with", never "caused by".
* `confidence` reflects only how tight the match is (same day vs adjacent day,
  how extreme the volume was, whether the ticker is named in the headline) —
  it is not a causal probability.
* Spikes with no matching news are reported as spikes with no explanation
  rather than being quietly dropped. An unexplained volume surge is itself
  information, and often more interesting than an explained one.
"""

import logging
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Volume must exceed this multiple of the rolling median to count as a spike.
# Median, not mean: a single 10x day drags a mean up enough to hide the next
# spike behind it.
SPIKE_MULTIPLE = 2.0
# Window for the rolling baseline, in bars.
BASELINE_WINDOW = 20
# How many days either side of a spike a headline may fall and still be linked.
# 1 covers news published after the close that moves the next session.
MATCH_WINDOW_DAYS = 1
# Cap on spikes reported, newest first — a chart annotated with thirty markers
# is unreadable.
MAX_SPIKES = 6


@dataclass
class VolumeEvent:
    """An unusual-volume bar and whatever news shares its date."""

    date: str                       # ISO date of the bar
    volume: int
    baseline: int                   # rolling median at that point
    multiple: float                 # volume / baseline
    close: float
    change_percent: Optional[float]  # same-bar price move
    headlines: List[Dict[str, Any]] = field(default_factory=list)
    confidence: str = "none"        # "high" | "medium" | "low" | "none"

    @property
    def explained(self) -> bool:
        return bool(self.headlines)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["explained"] = self.explained
        return d


def find_volume_spikes(
    df: pd.DataFrame,
    lookback: int = 90,
    multiple: float = SPIKE_MULTIPLE,
    window: int = BASELINE_WINDOW,
    limit: int = MAX_SPIKES,
) -> List[VolumeEvent]:
    """
    Bars whose volume exceeds `multiple` x the rolling median, newest first.

    The baseline is shifted by one bar so a spike is measured against the days
    BEFORE it — including the spike in its own baseline damps exactly the
    signal we're looking for.
    """
    if "Volume" not in df.columns or len(df) < window + 2:
        return []

    recent = df.tail(lookback)
    vol = recent["Volume"].astype(float)
    close = recent["Close"].astype(float)

    baseline = vol.rolling(window, min_periods=max(5, window // 2)).median().shift(1)
    prev_close = close.shift(1)

    events: List[VolumeEvent] = []
    for ts, v in vol.items():
        base = baseline.get(ts)
        if base is None or not np.isfinite(base) or base <= 0:
            continue
        mult = float(v) / float(base)
        if mult < multiple:
            continue
        pc = prev_close.get(ts)
        chg = (
            round((float(close[ts]) - float(pc)) / float(pc) * 100, 2)
            if pc and np.isfinite(pc) and pc > 0
            else None
        )
        events.append(
            VolumeEvent(
                date=ts.strftime("%Y-%m-%d"),
                volume=int(v),
                baseline=int(base),
                multiple=round(mult, 2),
                close=round(float(close[ts]), 4),
                change_percent=chg,
            )
        )

    events.sort(key=lambda e: e.date, reverse=True)
    return events[:limit]


def _base_ticker(symbol: str) -> str:
    """"BBCA.JK" -> "BBCA" — news tickers are stored unsuffixed."""
    return symbol.strip().upper().split(".")[0].lstrip("^")


def _score_match(
    event: VolumeEvent, item: Dict[str, Any], day_gap: int, base: str
) -> str:
    """
    Tightness of a news/spike pairing.

    Deliberately coarse. A finer number would imply a precision this cannot
    have — the underlying relationship is "these happened on the same day".
    """
    named = base in {t.upper() for t in (item.get("tickers") or [])}
    if day_gap == 0 and named and event.multiple >= 3.0:
        return "high"
    if day_gap == 0 and named:
        return "medium"
    if day_gap <= MATCH_WINDOW_DAYS and named:
        return "low"
    return "low"


def attach_news(
    events: Sequence[VolumeEvent],
    news: Sequence[Dict[str, Any]],
    symbol: str,
    per_event: int = 3,
) -> List[VolumeEvent]:
    """
    Pair each spike with same-window headlines mentioning the ticker.

    `news` items need `title`, `published_at`, and ideally `tickers`/`url`.
    Events with no match keep an empty `headlines` list — see the module
    docstring on why unexplained spikes are kept rather than dropped.
    """
    base = _base_ticker(symbol)
    if not events:
        return list(events)

    # Index headlines by calendar date once, rather than re-scanning per event.
    by_day: Dict[date, List[Dict[str, Any]]] = {}
    for item in news:
        raw = item.get("published_at") or item.get("publishedAt") or ""
        try:
            d = datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()
        except Exception:
            continue
        by_day.setdefault(d, []).append(item)

    for ev in events:
        try:
            ev_day = datetime.strptime(ev.date, "%Y-%m-%d").date()
        except ValueError:
            continue

        matches: List[Dict[str, Any]] = []
        best = "none"
        for offset in range(0, MATCH_WINDOW_DAYS + 1):
            for day in {ev_day - timedelta(days=offset), ev_day}:
                for item in by_day.get(day, []):
                    tickers = {t.upper() for t in (item.get("tickers") or [])}
                    if base not in tickers:
                        continue
                    conf = _score_match(ev, item, offset, base)
                    if any(m["title"] == item.get("title") for m in matches):
                        continue
                    matches.append({
                        "title": item.get("title"),
                        "source": item.get("source"),
                        "url": item.get("url"),
                        "importance": item.get("importance"),
                        "publishedAt": item.get("published_at") or item.get("publishedAt"),
                        "dayGap": offset,
                    })
                    order = {"high": 3, "medium": 2, "low": 1, "none": 0}
                    if order[conf] > order[best]:
                        best = conf
            if matches:
                break  # nearest day wins; don't dilute with older stories

        # High-importance headlines first, then most recent.
        matches.sort(
            key=lambda m: (
                {"high": 0, "medium": 1, "low": 2}.get(m.get("importance"), 3),
                m.get("dayGap", 9),
            )
        )
        ev.headlines = matches[:per_event]
        ev.confidence = best if matches else "none"

    return list(events)


def summarise(events: Sequence[VolumeEvent], currency: str = "IDR") -> Optional[str]:
    """
    One-paragraph Indonesian summary of what the volume did and why (or that
    no reason was found). Returns None when there were no spikes.
    """
    if not events:
        return None

    explained = [e for e in events if e.explained]
    parts = [
        f"Terdeteksi <b>{len(events)} lonjakan volume</b> dalam 90 hari terakhir"
    ]
    if explained:
        parts.append(f", {len(explained)} di antaranya bertepatan dengan berita emiten")
    parts.append(".")

    top = events[0]
    move = (
        f" harga bergerak {top.change_percent:+.2f}%"
        if top.change_percent is not None
        else ""
    )
    parts.append(
        f" Terbaru {top.date}: volume {top.multiple:.1f}x rata-rata,{move}."
    )
    if top.headlines:
        parts.append(f" Bertepatan dengan: “{top.headlines[0]['title']}”.")
    else:
        parts.append(
            " Tidak ada berita emiten yang terdeteksi pada tanggal itu — "
            "lonjakan tanpa katalis publik."
        )
    return "".join(parts)


def recent_for_ticker(
    news: Sequence[Dict[str, Any]], limit: int = 5
) -> List[Dict[str, Any]]:
    """
    The most recent headlines for a ticker, newest first — unfiltered.

    Deliberately NOT curated. No importance threshold, no sentiment screen, no
    dropping of unflattering stories: a reader forming conviction needs to see
    the bad news as readily as the good, and a feed that quietly hides negative
    coverage is worse than no feed because it looks complete.

    `news` is expected pre-filtered to the ticker by the caller (the repository
    query does this), so this only orders and truncates.
    """
    def when(item: Dict[str, Any]) -> str:
        return str(item.get("published_at") or item.get("publishedAt") or "")

    ordered = sorted(news, key=when, reverse=True)

    out: List[Dict[str, Any]] = []
    seen_titles = set()
    for item in ordered:
        title = (item.get("title") or "").strip()
        if not title or title in seen_titles:
            continue
        seen_titles.add(title)
        out.append({
            "title": title,
            "source": item.get("source"),
            "url": item.get("url"),
            "importance": item.get("importance"),
            "publishedAt": when(item),
            "isMsciAlert": bool(item.get("is_msci_alert") or item.get("isMsciAlert")),
        })
        if len(out) >= limit:
            break
    return out
