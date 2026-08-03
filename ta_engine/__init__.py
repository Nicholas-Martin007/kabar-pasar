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

__all__ = [
    "generate_chart",
    "ChartResult",
    "DISCLAIMER",
    "Level",
    "add_indicators",
    "build_levels",
    "nearest_levels",
]
