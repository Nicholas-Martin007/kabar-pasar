"""
Technical-analysis engine.

Computes indicators over daily OHLCV (via `yfinance` + `ta`) and renders
annotated candlestick charts (via `mplfinance`) into `static/charts/` for
delivery through the Telegram bot and the dashboard.

    from ta_engine import generate_chart
    result = generate_chart("BBCA.JK")

Levels produced here are mechanical arithmetic on historical prices, not
investment advice — see `chart_generator.DISCLAIMER`.
"""

from .chart_generator import DISCLAIMER, ChartResult, generate_chart
from .indicators import Level, add_indicators, build_levels, nearest_levels
from .support_resistance import Zone, build_zones, nearest_zones

__all__ = [
    "generate_chart",
    "ChartResult",
    "DISCLAIMER",
    "add_indicators",
    # Scored S/R zones — what everything user-facing should use.
    "Zone",
    "build_zones",
    "nearest_zones",
    # Legacy single-price levels. Superseded by the zone API above: these
    # measure no strength, mix formulaic pivots into their touch counts, and
    # collapse a band to one number. Kept only so nothing external breaks.
    "Level",
    "build_levels",
    "nearest_levels",
]
