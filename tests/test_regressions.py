"""
Regressions for bugs that actually happened, not hypothetical ones.

Three classes recurred repeatedly while this engine was built, and each cost
real debugging time:

1. **Silent string-replacement failures.** Patching a Python source file by
   text substitution "succeeds" while changing nothing when the anchor drifts.
   `/msci` in HELP, `/lot` in HELP and the FTSE patterns all shipped as no-ops.
   Fix: assert that every registered command is discoverable in help text.
2. **Rounding drift between surfaces.** The same level printed differently in
   the API payload, the chart label and the Telegram caption — 5,675 vs 5,681,
   POC 6,150 vs 6,153. Fixed three separate times.
3. **Dangling references after a rename.** `_RIGHT_MARGIN_BARS` was renamed and
   four call sites were left behind; every chart raised NameError until the
   next render was attempted.

Each of those is cheap to assert and expensive to find by hand.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


# ── 1. Command registration vs help text ─────────────────────────────────────


def _telegram_source() -> str:
    return (ROOT / "telegram_bot" / "telegram_service.py").read_text(encoding="utf-8")


def test_every_dispatched_command_appears_in_help():
    """
    Any command the bot answers must be findable in HELP or _PAPER_HELP.

    This is the check that would have caught /msci and /lot being "added" to
    the help text by patches that silently matched nothing.
    """
    import telegram_bot.telegram_service as tg

    src = _telegram_source()
    # Commands the dispatcher tests for, e.g. cmd == "ihsg" / cmd in ("a", "b").
    single = set(re.findall(r'cmd == "([a-z]+)"', src))
    grouped = set()
    for group in re.findall(r'cmd in \(([^)]*)\)', src):
        grouped.update(re.findall(r'"([a-z]+)"', group))

    documented = (tg.HELP + tg._PAPER_HELP).lower()
    # Aliases and internal/undocumented commands stay out of the help text on
    # purpose; only the primary names are contractual.
    exempt = {
        "test", "start", "portfolio", "porto", "posisi", "trade", "simulasi",
        "resetakun", "size", "sizing", "ftse", "indeks", "unmute", "unfollow",
        "unwatch", "all", "important", "mute", "follow", "watch", "help",
    }
    missing = sorted(
        c for c in (single | grouped) - exempt if f"/{c}" not in documented
    )
    assert not missing, f"commands answered but absent from help: {missing}"


def test_help_text_has_no_unclosed_html_tags():
    """Telegram rejects the whole message on malformed HTML, silently to us."""
    import telegram_bot.telegram_service as tg

    for name, text in (("HELP", tg.HELP), ("_PAPER_HELP", tg._PAPER_HELP)):
        opened = re.findall(r"<([a-z]+)>", text)
        closed = re.findall(r"</([a-z]+)>", text)
        assert sorted(opened) == sorted(closed), f"{name} has unbalanced tags"


# ── 2. Rounding agreement across surfaces ────────────────────────────────────


@pytest.mark.parametrize(
    "price,direction,expected_multiple",
    [(2003, "floor", 10), (2003, "ceil", 10), (6312, "nearest", 25), (151, "ceil", 1)],
)
def test_idx_rounding_lands_on_the_tick_grid(price, direction, expected_multiple):
    from ta_engine.price_utils import idx_tick_size, round_to_idx_tick

    out = round_to_idx_tick(price, direction)
    assert out % idx_tick_size(out) == 0
    assert idx_tick_size(price) == expected_multiple


def test_rounding_directions_never_cross_the_input():
    """floor must not round up and ceil must not round down — the stop and the
    target both depend on rounding AWAY from entry to preserve the R multiple."""
    from ta_engine.price_utils import round_to_idx_tick

    for p in (2003, 2007, 6311, 151, 5002):
        assert round_to_idx_tick(p, "floor") <= p
        assert round_to_idx_tick(p, "ceil") >= p


def test_zone_payload_and_narrative_quote_the_same_band(indicators_df):
    """
    The band in the payload must be the band in the Telegram text.

    Payload rounding to the tick grid while the caption formatted the raw float
    is exactly how 5,675-6,525 ended up printed next to 5,681-6,502.
    """
    from ta_engine.chart_generator import _zone_dict
    from ta_engine.narrative import _zone_lines
    from ta_engine.support_resistance import build_zones, nearest_zones

    atr = float(indicators_df["atr14"].iloc[-1])
    price = float(indicators_df["Close"].iloc[-1])
    support, _ = nearest_zones(price, build_zones(indicators_df, atr, price))
    if support is None:
        pytest.skip("synthetic series produced no support zone")

    payload = _zone_dict(support, "BBCA.JK")
    text = " ".join(_zone_lines("🟢", "Support", payload, None, "IDR"))
    assert f"{payload['low']:,.0f}" in text
    assert f"{payload['high']:,.0f}" in text


# ── 3. Dangling references / import health ───────────────────────────────────


def test_ta_engine_modules_all_import():
    """
    A rename that leaves call sites behind only surfaces on the next render.

    Importing every module catches missing names at module scope; the render
    test below catches them inside functions.
    """
    import importlib

    for mod in (
        "ta_engine.indicators",
        "ta_engine.price_utils",
        "ta_engine.support_resistance",
        "ta_engine.volume_profile",
        "ta_engine.pattern_detector",
        "ta_engine.narrative",
        "ta_engine.chart_generator",
        "ta_engine.screener",
        "ta_engine.zone_backtest",
        "ta_engine.pattern_backtest",
    ):
        importlib.import_module(mod)


def test_no_undefined_module_constants_in_chart_generator():
    """
    Every _UPPER_CASE name used in chart_generator must be defined there or
    imported. `_RIGHT_MARGIN_BARS` survived a rename in four call sites and
    broke every chart.
    """
    import ta_engine.chart_generator as cg

    src = Path(cg.__file__).read_text(encoding="utf-8")
    used = set(re.findall(r"\b(_[A-Z][A-Z0-9_]{2,})\b", src))
    missing = sorted(n for n in used if not hasattr(cg, n))
    assert not missing, f"referenced but undefined in chart_generator: {missing}"
