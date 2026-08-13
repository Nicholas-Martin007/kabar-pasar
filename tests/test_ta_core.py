"""
Core TA and IDX-mechanics invariants.

These assert the properties the engine's honesty depends on — that a stop is
wider than the level it protects, that a boundary caps the pivots it was fitted
to, that a "strong" label cannot be handed to a level that mostly breaks. Where
a constant was tuned by measurement, the test pins the PROPERTY rather than the
number, so recalibrating stays possible without rewriting the suite.
"""

import math

import numpy as np
import pandas as pd
import pytest

from tests.conftest import make_ohlcv


# ── IDX mechanics ────────────────────────────────────────────────────────────


def test_round_trip_costs_make_breakeven_above_entry():
    """Buying and selling at the same price must LOSE money. A simulator where
    it doesn't teaches that scalping is free."""
    from backend.services.idx_rules import breakeven_price, buy_cost, sell_proceeds

    buy = buy_cost(2000, 50)
    sell = sell_proceeds(2000, 50)
    assert sell.net < buy.net
    assert breakeven_price(2000) > 2000
    # BOTH legs must charge. Asserting only that a round trip loses money
    # passes with a zero buy fee, because the sell fee alone covers it — a
    # mutation test caught exactly that hole.
    assert buy.fee > 0 and buy.net > buy.gross
    assert sell.fee > 0 and sell.net < sell.gross


def test_ara_arb_band_widens_for_cheap_stocks():
    """IDX allows a bigger daily move on low-priced shares."""
    from backend.services.idx_rules import ara_arb_limits

    lo_cheap, hi_cheap = ara_arb_limits(100)
    lo_blue, hi_blue = ara_arb_limits(8000)
    assert (hi_cheap / 100 - 1) > (hi_blue / 8000 - 1)
    assert lo_cheap < 100 < hi_cheap


def test_position_size_risk_matches_requested_budget():
    from backend.services.idx_rules import size_position

    eq = 100_000_000
    ps = size_position(eq, eq, entry=2000, stop=1900, risk_pct=1.0)
    assert ps is not None
    # Lot granularity means it lands at or just under the budget, never over.
    assert ps.risk_pct_of_equity <= 1.0
    assert ps.risk_pct_of_equity > 0.9
    assert ps.lots >= 1


def test_position_size_rejects_stop_above_entry():
    from backend.services.idx_rules import size_position

    assert size_position(1e8, 1e8, entry=2000, stop=2100, risk_pct=1) is None


def test_position_size_is_capped_by_available_cash():
    from backend.services.idx_rules import size_position

    ps = size_position(equity=1e8, cash=5_000_000, entry=2000, stop=1900, risk_pct=2)
    assert ps is not None and ps.capped_by_cash
    assert ps.cost <= 5_000_000


# ── Entry planning ───────────────────────────────────────────────────────────


def test_entry_zone_never_sits_at_or_above_market():
    """
    The anti-HAKA invariant: a pullback entry must be BELOW the last price.

    Quoting "ideal buy" at the current price is what tells a reader that
    chasing the offer is fine.
    """
    from ta_engine.price_utils import build_entry_plan

    plan = build_entry_plan(
        close=4240, atr=90, support=4200, stop_loss=4050, tp1=4600,
        ticker="BMRI.JK", direction="long",
    )
    if plan.get("entry_high") and plan.get("entry_type") == "pullback":
        assert plan["entry_high"] < 4240
        # And it must be a ZONE. A collapsed band is a single price, which is
        # the precision the zone exists to avoid implying.
        assert plan["entry_low"] < plan["entry_high"]


# ── Support / resistance zones ───────────────────────────────────────────────


def test_zone_is_a_band_not_a_line(indicators_df):
    from ta_engine.support_resistance import build_zones

    atr = float(indicators_df["atr14"].iloc[-1])
    zones = build_zones(indicators_df, atr, use_htf=False)
    assert zones, "expected at least one zone on a 260-bar series"
    for z in zones:
        assert z.high > z.low
        assert z.low <= z.mid <= z.high


def test_strong_label_requires_a_real_hold_record():
    """
    A level that mostly breaks cannot be KUAT, whatever its prominence.

    This is the cap that fixed the first calibration, where a band with
    "15 tes, 6 bertahan, 9 jebol" was rated strong.
    """
    from ta_engine.support_resistance import _score_zone, _strength_of

    score, hold_ratio, _ = _score_zone(
        tests=15, holds=6, breaks=9, bars_since=0,
        volume_share=0.20, span=80, flipped=True,
    )
    assert _strength_of(score, hold_ratio, holds := 6 + 9) != "strong"


def test_perfect_record_can_still_be_strong():
    """The cap must not make KUAT unreachable — that would be a different bug."""
    from ta_engine.support_resistance import _score_zone, _strength_of

    score, hold_ratio, _ = _score_zone(
        tests=10, holds=9, breaks=1, bars_since=2,
        volume_share=0.20, span=80, flipped=True,
    )
    assert _strength_of(score, hold_ratio, 10) == "strong"


def test_weekly_confluence_does_not_change_the_score():
    """
    Measured at zero on purpose. If someone re-enables the bonus, this test
    should fail and send them to the backtest that zeroed it.
    """
    from ta_engine.support_resistance import _score_zone

    without, _, _ = _score_zone(6, 4, 2, 5, 0.1, 40, False, False)
    with_htf, _, _ = _score_zone(6, 4, 2, 5, 0.1, 40, False, True)
    assert with_htf == pytest.approx(without)


def _zone(low, high, strength="medium"):
    from ta_engine.support_resistance import Zone

    return Zone(
        low=low, high=high, mid=(low + high) / 2, kind="support",
        flipped=False, htf_confluence=False, tests=5, holds=3, breaks=2,
        bars_since_test=3, volume_share=0.05, span_bars=40,
        score=0.5, strength=strength,
    )


def test_nearest_zones_uses_band_edges_not_midpoints():
    """
    A zone straddling the price is neither support nor resistance.

    Selecting on `mid` would return a band price is currently INSIDE as the
    nearest support, and the published level would sit above the last close.
    """
    from ta_engine.support_resistance import nearest_zones

    # Straddles price AND has its midpoint below it (995 < 1000 < 1010), which
    # is the only shape that distinguishes edge-selection from mid-selection.
    # A first attempt used (995, 1010) — mid 1002.5, above price — so the
    # mutation it was written to catch sailed through.
    # Two straddlers are needed, one either side of the midpoint: the support
    # branch and the resistance branch fail independently, and a single
    # straddler only exercises whichever one its mid happens to fall on.
    straddle_lowmid = _zone(980, 1010)    # mid 995  — trips the support branch
    straddle_highmid = _zone(995, 1030)   # mid 1012 — trips the resistance branch
    clean_support = _zone(940, 960)
    clean_resist = _zone(1040, 1060)
    zones = [straddle_lowmid, straddle_highmid, clean_support, clean_resist]

    sup, res = nearest_zones(1000, zones)
    assert sup is clean_support, "a band containing price is not support"
    assert res is clean_resist, "a band containing price is not resistance"
    assert sup.high < 1000 < res.low


def test_anchor_zone_prefers_strength_over_proximity():
    """
    The defect that started the zone rewrite: the stop hung off whatever level
    was nearest, however badly it had held.
    """
    from ta_engine.support_resistance import Zone, anchor_zone

    def zone(low, high, strength):
        return Zone(
            low=low, high=high, mid=(low + high) / 2, kind="support",
            flipped=False, htf_confluence=False, tests=5, holds=3, breaks=2,
            bars_since_test=3, volume_share=0.05, span_bars=40,
            score=0.5, strength=strength,
        )

    near_weak = zone(980, 990, "weak")
    far_strong = zone(900, 920, "strong")
    anchor, nearest = anchor_zone(1000, [near_weak, far_strong], "support", atr=30)
    assert nearest is near_weak
    assert anchor is far_strong


# ── Volume profile ───────────────────────────────────────────────────────────


def test_value_area_holds_about_seventy_percent(indicators_df):
    from ta_engine.volume_profile import VALUE_AREA_PCT, build_profile

    atr = float(indicators_df["atr14"].iloc[-1])
    prof = build_profile(indicators_df, atr)
    assert prof is not None
    share = prof.volume_between(prof.val, prof.vah)
    assert share == pytest.approx(VALUE_AREA_PCT, abs=0.06)
    assert prof.val <= prof.poc <= prof.vah


def test_profile_flags_itself_wide_when_volume_is_smeared():
    """ASPR ran 99 -> 620 -> 156; a 160%-wide 'value area' is not a level."""
    from ta_engine.volume_profile import build_profile

    df = make_ohlcv(n=200, start=100, seed=3, trend=0.02)  # strong drift
    from ta_engine.indicators import add_indicators

    df = add_indicators(df)
    prof = build_profile(df, float(df["atr14"].iloc[-1]), bars=None)
    assert prof is not None
    assert prof.is_wide is ((prof.vah - prof.val) / prof.poc > 0.45)


# ── Pattern boundaries ───────────────────────────────────────────────────────


def test_fitted_boundary_caps_its_own_pivots():
    """
    An upper boundary must sit AT or ABOVE every pivot it was fitted to.

    A least-squares fit runs through the middle and leaves half the pivots
    above the line, which is what made ICBP's breakout level a price the stock
    had already traded through.
    """
    from ta_engine.pattern_detector import Pivot, fit_boundary

    ts = pd.Timestamp("2024-01-01")
    highs = [
        Pivot(0, ts, 100.0, "high"),
        Pivot(10, ts, 108.0, "high"),
        Pivot(20, ts, 104.0, "high"),
        Pivot(30, ts, 112.0, "high"),
    ]
    slope, intercept, _ = fit_boundary(highs, "upper", tol=0.0)
    for p in highs:
        assert slope * p.idx + intercept >= p.price - 1e-6

    slope, intercept, _ = fit_boundary(highs, "lower", tol=0.0)
    for p in highs:
        assert slope * p.idx + intercept <= p.price + 1e-6


def test_build_trendline_actually_routes_to_the_boundary_fit():
    """
    Cover the DISPATCH, not just the helper.

    Testing fit_boundary directly left the `if side:` branch in build_trendline
    unguarded — a mutation that reverted it to least-squares passed the whole
    suite. The detectors call build_trendline, so that is the surface that
    matters.
    """
    from ta_engine.pattern_detector import Pivot, build_trendline

    ts = pd.Timestamp("2024-01-01")
    highs = [
        Pivot(0, ts, 100.0, "high"),
        Pivot(10, ts, 108.0, "high"),
        Pivot(20, ts, 104.0, "high"),
        Pivot(30, ts, 112.0, "high"),
    ]
    line = build_trendline(highs, highs, side="upper", tol=0.0)
    above = [p for p in highs if p.price > line.value_at(p.idx) + 1e-6]
    assert not above, "upper boundary left pivots above it — regression fit?"


def test_pattern_track_record_flags_anti_predictive_patterns():
    """Bear Pennant measured -20pp; it must not be presented as helpful."""
    from ta_engine.pattern_detector import pattern_track_record

    assert pattern_track_record("Bear Pennant")["verdict"] == "hurts"
    assert pattern_track_record("Falling Wedge")["verdict"] == "helps"
    # Too thin to quote at all.
    assert pattern_track_record("Bull Flag") is None


def test_invalidated_pattern_is_detected():
    """A bearish pattern that broke UP must be reported as refuted."""
    from ta_engine.chart_generator import pattern_invalidated
    from ta_engine.pattern_detector import Pattern

    p = Pattern(
        pattern_type="Rising Wedge", quality_score=0.9, is_reversal=True,
        lines=[], key_levels={}, direction="bearish",
        start_ts=pd.Timestamp("2024-01-01"), end_ts=pd.Timestamp("2024-02-01"),
        start_idx=0, end_idx=10, volume_confirmed=False,
        resolution="broke_up", resolution_atr=1.9,
    )
    assert pattern_invalidated(p) is True
    p.resolution = "broke_down"
    assert pattern_invalidated(p) is False


# ── Indicators ───────────────────────────────────────────────────────────────


def test_atr_warmup_is_nan_not_zero(indicators_df):
    """
    A literal 0 ATR reads as 'no volatility' and collapses the stop to nothing.
    The `ta` library emits 0.0 during warm-up; we mask it.
    """
    from ta_engine.indicators import ATR_WINDOW

    warm = indicators_df["atr14"].iloc[: ATR_WINDOW - 1]
    assert warm.isna().all()
    assert (indicators_df["atr14"].dropna() > 0).all()


def test_stochastic_stays_within_bounds(indicators_df):
    for col in ("stoch_k", "stoch_d"):
        vals = indicators_df[col].dropna()
        assert not vals.empty
        assert vals.between(0, 100).all()
