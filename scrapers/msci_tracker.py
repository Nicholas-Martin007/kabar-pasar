"""
MSCI index-review tracker.

MSCI rebalancing moves large, mechanical foreign flows through IDX names —
index funds must trade the additions and deletions regardless of view — so
these headlines are treated as their own alert class rather than competing
with ordinary market news for attention.

Two jobs:

1. **Detection.** Every ingested item is checked for MSCI references. A match
   sets `is_msci_alert` and `priority="HIGH"`, and the alert path lets those
   bypass per-subscriber filters.
2. **Calendar.** MSCI publishes on a fixed quarterly rhythm (Feb/May/Aug/Nov).
   Reminders fire 3 days ahead and on the day, so the desk is positioned before
   the announcement rather than reacting to it.

## Matching is deliberately conservative

"MSCI" is a short token that appears inside unrelated words and tickers, so the
patterns are word-boundary anchored and case-insensitive. The cost asymmetry
runs one way here: a missed MSCI review is a missed repositioning window, but a
false positive is a screaming 🚨 push for an article about something else,
which trains the user to ignore the badge. Precision protects the signal.
"""

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

PRIORITY_HIGH = "HIGH"
PRIORITY_NORMAL = "NORMAL"

# Word-boundary anchored so "MSCI" doesn't match inside a longer token. The
# Indonesian phrasings matter as much as the English ones — local outlets
# usually write "kocok ulang" rather than "rebalancing".
_MSCI_PATTERNS: Sequence[re.Pattern] = (
    re.compile(r"\bMSCI\b", re.IGNORECASE),
    re.compile(r"\bmorgan\s+stanley\s+capital\s+international\b", re.IGNORECASE),
    re.compile(r"\bkocok\s+ulang\b", re.IGNORECASE),
)

# Extra context that raises confidence when "MSCI" alone is ambiguous. Used for
# classifying the event, not for gating the alert.
_REVIEW_HINTS: Sequence[re.Pattern] = (
    re.compile(r"\brebalanc\w*\b", re.IGNORECASE),
    re.compile(r"\bindex\s+review\b", re.IGNORECASE),
    re.compile(r"\bglobal\s+standard\b", re.IGNORECASE),
    re.compile(r"\bsmall\s*cap\b", re.IGNORECASE),
    re.compile(r"\b(inclusion|exclusion|masuk|keluar|dikeluarkan)\b", re.IGNORECASE),
    re.compile(r"\b(konstituen|constituent)\b", re.IGNORECASE),
)


@dataclass(frozen=True)
class MSCIReview:
    """One scheduled MSCI index review."""

    name: str
    announcement: date
    kind: str  # "Quarterly" | "Semi-Annual"

    @property
    def label(self) -> str:
        return f"{self.name} ({self.kind} Index Review)"


# MSCI's published rhythm: February and August are Quarterly Index Reviews;
# May and November are Semi-Annual Index Reviews. Announcement dates land in
# the second week of the month, effective after the last business day.
#
# NOTE: these are SCHEDULED dates entered from MSCI's public calendar, not
# scraped. MSCI shifts them occasionally, so treat a reminder as "check the
# official calendar", not as a confirmed timestamp. Update annually.
_REVIEW_CALENDAR: List[MSCIReview] = [
    MSCIReview("February 2026 Review", date(2026, 2, 10), "Quarterly"),
    MSCIReview("May 2026 Review", date(2026, 5, 12), "Semi-Annual"),
    MSCIReview("August 2026 Review", date(2026, 8, 11), "Quarterly"),
    MSCIReview("November 2026 Review", date(2026, 11, 10), "Semi-Annual"),
    MSCIReview("February 2027 Review", date(2027, 2, 9), "Quarterly"),
    MSCIReview("May 2027 Review", date(2027, 5, 11), "Semi-Annual"),
    MSCIReview("August 2027 Review", date(2027, 8, 10), "Quarterly"),
    MSCIReview("November 2027 Review", date(2027, 11, 9), "Semi-Annual"),
]

# Days before an announcement that trigger a heads-up.
REMINDER_LEAD_DAYS = 3


# ── Detection ────────────────────────────────────────────────────────────────


def is_msci_news(title: str, body: str = "") -> bool:
    """True when the text references MSCI or an index shake-up."""
    text = f"{title} {body}"
    return any(p.search(text) for p in _MSCI_PATTERNS)


def classify_msci(title: str, body: str = "") -> Dict[str, Any]:
    """
    Detection result plus the hints that produced it.

    `confidence` is a coarse signal for ranking, not a probability: "high" means
    an MSCI reference AND review context, "medium" means the reference alone.
    """
    text = f"{title} {body}"
    matched = [p.pattern for p in _MSCI_PATTERNS if p.search(text)]
    if not matched:
        return {
            "is_msci_alert": False,
            "priority": PRIORITY_NORMAL,
            "confidence": "none",
            "matched": [],
            "hints": [],
        }

    hints = [p.pattern for p in _REVIEW_HINTS if p.search(text)]
    return {
        "is_msci_alert": True,
        "priority": PRIORITY_HIGH,
        "confidence": "high" if hints else "medium",
        "matched": matched,
        "hints": hints,
    }


def tag_items(items: Sequence[Any]) -> List[Any]:
    """
    Return the subset of `items` that are MSCI-related.

    Accepts anything exposing `.title` and `.excerpt` (the News model) so this
    stays usable from both the fast poller and the scheduled refresh.
    """
    out = []
    for item in items:
        title = getattr(item, "title", "") or ""
        body = getattr(item, "excerpt", "") or ""
        if is_msci_news(title, body):
            out.append(item)
    if out:
        logger.info("msci.detected count=%d of %d", len(out), len(items))
    return out


# ── Calendar ─────────────────────────────────────────────────────────────────


def upcoming_reviews(today: Optional[date] = None, limit: int = 4) -> List[MSCIReview]:
    """Scheduled reviews on or after `today`, soonest first."""
    today = today or datetime.now(timezone.utc).date()
    return [r for r in _REVIEW_CALENDAR if r.announcement >= today][:limit]


def next_review(today: Optional[date] = None) -> Optional[MSCIReview]:
    nxt = upcoming_reviews(today, limit=1)
    return nxt[0] if nxt else None


def due_reminders(today: Optional[date] = None) -> List[Dict[str, Any]]:
    """
    Reviews needing a reminder today: exactly `REMINDER_LEAD_DAYS` out, or today.

    Only those two exact offsets fire — a range would re-alert every day of the
    lead-up and the notification would stop meaning anything.
    """
    today = today or datetime.now(timezone.utc).date()
    out: List[Dict[str, Any]] = []
    for r in _REVIEW_CALENDAR:
        delta = (r.announcement - today).days
        if delta == REMINDER_LEAD_DAYS:
            out.append({"review": r, "days_out": delta, "stage": "upcoming"})
        elif delta == 0:
            out.append({"review": r, "days_out": 0, "stage": "today"})
    return out


def calendar_snapshot(today: Optional[date] = None) -> Dict[str, Any]:
    """Serialisable calendar view for the API / debugging."""
    today = today or datetime.now(timezone.utc).date()
    nxt = next_review(today)
    return {
        "today": today.isoformat(),
        "reminderLeadDays": REMINDER_LEAD_DAYS,
        "next": (
            {
                "name": nxt.name,
                "kind": nxt.kind,
                "announcement": nxt.announcement.isoformat(),
                "daysOut": (nxt.announcement - today).days,
            }
            if nxt
            else None
        ),
        "upcoming": [
            {
                "name": r.name,
                "kind": r.kind,
                "announcement": r.announcement.isoformat(),
                "daysOut": (r.announcement - today).days,
            }
            for r in upcoming_reviews(today)
        ],
        "note": (
            "Scheduled from MSCI's published calendar, not scraped. MSCI can "
            "move these — confirm against the official announcement."
        ),
    }
