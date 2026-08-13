"""
Shared fixtures.

Everything here is OFFLINE. Not one test may touch yfinance, the Telegram API
or the live DB: a suite that needs the network is a suite people stop running,
and this one exists to be run on every change.
"""

import numpy as np
import pandas as pd
import pytest


def make_ohlcv(
    n: int = 260,
    start: float = 1000.0,
    seed: int = 7,
    trend: float = 0.0,
) -> pd.DataFrame:
    """
    Deterministic synthetic OHLCV with a business-day index.

    Seeded so a failure is reproducible — a random walk that only fails on
    Tuesdays is worse than no test at all.
    """
    rng = np.random.default_rng(seed)
    steps = rng.normal(trend, 0.015, n)
    close = start * np.exp(np.cumsum(steps))
    spread = np.abs(rng.normal(0, 0.008, n)) * close
    high = close + spread
    low = np.maximum(close - spread, 1e-6)
    open_ = np.concatenate([[start], close[:-1]])
    volume = rng.integers(1_000_000, 9_000_000, n).astype(float)

    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {"Open": open_, "High": np.maximum(high, np.maximum(open_, close)),
         "Low": np.minimum(low, np.minimum(open_, close)),
         "Close": close, "Volume": volume},
        index=idx,
    )


@pytest.fixture
def ohlcv() -> pd.DataFrame:
    return make_ohlcv()


@pytest.fixture
def indicators_df(ohlcv: pd.DataFrame) -> pd.DataFrame:
    from ta_engine.indicators import add_indicators
    return add_indicators(ohlcv)
