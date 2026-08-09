"""
Fundamental snapshot to sit alongside the technicals.

Valuation and quality metrics from yfinance — PER, PBV, ROE, dividend yield,
margins, growth, sector — so a chart answers "is this cheap and does it earn
money", not only "which way has it been going".

## Every value is validated before it is shown

Yahoo's fundamental data for IDX names is materially less reliable than its
price data. Verified example: PTRO.JK reports `bookValue = 0.026` and therefore
`priceToBook = 197115`, which is nonsense — the book value is in the wrong
scale. BBCA's equivalent figures are sane.

So each metric is bounds-checked and dropped when implausible, rather than
displayed raw. A missing PBV is a small gap in the UI; a PBV of 197,115 shown
to a retail investor is misinformation they might act on. `suppressed` records
what was dropped and why, so the omission is visible rather than silent.

These are point-in-time vendor figures, not audited statements, and they lag
the filings they come from. Treat them as a screen, not a valuation.
"""

import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Plausibility bounds. Deliberately wide — the job is catching data errors, not
# judging whether a valuation is attractive.
_BOUNDS: Dict[str, tuple] = {
    # A PER over ~300 is either a near-zero-earnings company or bad data; either
    # way the number carries no information for a retail screen.
    "per": (0.1, 300.0),
    "forward_per": (0.1, 300.0),
    # PBV above 50 on IDX is almost always a book-value scale error (see PTRO).
    "pbv": (0.01, 50.0),
    # ROE beyond +/-200% is not a real sustained return.
    "roe_percent": (-200.0, 200.0),
    # Yahoo has historically mixed fraction and percent for yield; anything
    # above 100% is definitionally broken.
    "dividend_yield_percent": (0.0, 100.0),
    "profit_margin_percent": (-500.0, 100.0),
    "earnings_growth_percent": (-1000.0, 1000.0),
    "revenue_growth_percent": (-1000.0, 1000.0),
    "debt_to_equity": (0.0, 2000.0),
}


@dataclass
class Fundamentals:
    ticker: str
    sector: Optional[str] = None
    industry: Optional[str] = None
    market_cap: Optional[float] = None
    per: Optional[float] = None
    forward_per: Optional[float] = None
    pbv: Optional[float] = None
    roe_percent: Optional[float] = None
    dividend_yield_percent: Optional[float] = None
    profit_margin_percent: Optional[float] = None
    earnings_growth_percent: Optional[float] = None
    revenue_growth_percent: Optional[float] = None
    debt_to_equity: Optional[float] = None
    eps: Optional[float] = None
    book_value: Optional[float] = None
    # Metrics dropped by validation, as {field: reason}. Surfaced so a gap in
    # the UI is explained rather than looking like a fetch failure.
    suppressed: Dict[str, str] = field(default_factory=dict)
    available: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _clean(name: str, value: Any, suppressed: Dict[str, str]) -> Optional[float]:
    """Coerce to float and bounds-check, recording why anything was dropped."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v != v:  # NaN
        return None

    lo, hi = _BOUNDS.get(name, (float("-inf"), float("inf")))
    if not (lo <= v <= hi):
        suppressed[name] = (
            f"{v:,.4g} outside plausible range {lo:g}..{hi:g} — treated as bad "
            f"vendor data, not displayed"
        )
        logger.info("fundamentals.suppressed field=%s value=%s", name, v)
        return None
    return round(v, 4)


def _as_percent(value: Any) -> Any:
    """
    Yahoo returns some ratios as fractions (0.218 = 21.8%) and yield sometimes
    already as a percent. Scale fractions up, leave anything already >1 alone.
    """
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v * 100.0 if -1.0 <= v <= 1.0 else v


def fetch_fundamentals(ticker: str) -> Fundamentals:
    """
    Blocking yfinance `.info` lookup. Run via asyncio.to_thread from async code.

    Never raises for a missing metric — an absent fundamental is normal and the
    chart is still useful without it.
    """
    import yfinance as yf

    out = Fundamentals(ticker=ticker.upper())
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception as exc:
        logger.warning("fundamentals.fetch_failed ticker=%s error=%s", ticker, exc)
        return out

    sup = out.suppressed
    out.sector = info.get("sector")
    out.industry = info.get("industry")
    out.market_cap = _clean("market_cap", info.get("marketCap"), sup)
    out.per = _clean("per", info.get("trailingPE"), sup)
    out.forward_per = _clean("forward_per", info.get("forwardPE"), sup)
    out.pbv = _clean("pbv", info.get("priceToBook"), sup)
    out.roe_percent = _clean("roe_percent", _as_percent(info.get("returnOnEquity")), sup)
    # dividendYield is ALREADY a percent in current yfinance (BBCA reports 5.58
    # for ~5.6%), unlike returnOnEquity/profitMargins which are fractions.
    # Running it through _as_percent turned PTRO's genuine 0.3% into 30% — a
    # 100x overstatement of income on a stock someone might buy for yield.
    out.dividend_yield_percent = _clean(
        "dividend_yield_percent", info.get("dividendYield"), sup
    )
    out.profit_margin_percent = _clean(
        "profit_margin_percent", _as_percent(info.get("profitMargins")), sup
    )
    out.earnings_growth_percent = _clean(
        "earnings_growth_percent", _as_percent(info.get("earningsGrowth")), sup
    )
    out.revenue_growth_percent = _clean(
        "revenue_growth_percent", _as_percent(info.get("revenueGrowth")), sup
    )
    out.debt_to_equity = _clean("debt_to_equity", info.get("debtToEquity"), sup)
    out.eps = _clean("eps", info.get("trailingEps"), sup)
    out.book_value = _clean("book_value", info.get("bookValue"), sup)

    # Cross-check: PBV should roughly equal price / book value. A large mismatch
    # means one of the two is on the wrong scale even if both passed bounds.
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    if out.pbv and out.book_value and price:
        try:
            implied = float(price) / float(out.book_value)
            if implied > 0 and not (0.2 <= implied / out.pbv <= 5.0):
                sup["pbv"] = (
                    f"inconsistent with price/book ({implied:,.1f} vs reported "
                    f"{out.pbv:,.2f}) — vendor scale error, not displayed"
                )
                out.pbv = None
        except (TypeError, ValueError, ZeroDivisionError):
            pass

    out.available = any(
        v is not None
        for v in (out.per, out.pbv, out.roe_percent, out.dividend_yield_percent)
    )
    return out


def summarise(f: Fundamentals) -> Optional[str]:
    """Short Indonesian valuation line, or None when nothing survived validation."""
    if not f.available:
        return None
    bits: List[str] = []
    if f.per is not None:
        bits.append(f"PER {f.per:.1f}x")
    if f.pbv is not None:
        bits.append(f"PBV {f.pbv:.2f}x")
    if f.roe_percent is not None:
        bits.append(f"ROE {f.roe_percent:.1f}%")
    if f.dividend_yield_percent is not None:
        bits.append(f"dividend yield {f.dividend_yield_percent:.2f}%")
    if not bits:
        return None
    head = f"{f.sector}: " if f.sector else ""
    return head + " · ".join(bits)
