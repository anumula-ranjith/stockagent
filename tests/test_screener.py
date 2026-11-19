import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from stock_agents.api.screener import History, Screen, ema, evaluate, signal


def fixture_history():
    dates = pd.bdate_range("2024-01-01", periods=300)
    values = pd.DataFrame(95.0, index=dates, columns=["FULL", "IPO"])
    values.loc[dates[:-40], "IPO"] = np.nan
    # The prior high/low are intraday highs/lows. A split changed the raw price units.
    return History(values.columns, values, values * (100 / 95), values * (75 / 95), values * 2)


def test_range_filters_and_price_units():
    history = fixture_history()
    rows = evaluate(history, Screen(below_high_pct=5, above_low_pct=27))["rows"]
    assert [r["ticker"] for r in rows] == ["FULL"]
    row = rows[0]
    assert (row["close"], row["high_52w"], row["low_52w"], row["below_high_pct"]) == (
        190,
        200,
        150,
        5,
    )
    assert evaluate(history, Screen(below_high_pct=4.99))["rows"] == []
    assert evaluate(history, Screen(above_low_pct=25))["rows"] == []
    unfiltered = evaluate(history, Screen())
    assert unfiltered["range_coverage"] == 1 and unfiltered["members"] == 2
    assert unfiltered["rows"][1]["high_52w"] is None


def test_multiple_52_week_levels_support_bands_and_any_match():
    history = fixture_history()
    band = Screen(range_levels=[
        {"metric": "below_high_pct", "operator": "at_least", "value": 5},
        {"metric": "below_high_pct", "operator": "at_most", "value": 15},
    ])
    assert [row["ticker"] for row in evaluate(history, band)["rows"]] == ["FULL"]
    impossible = band.model_copy(update={"range_levels": [
        band.range_levels[0], band.range_levels[1].model_copy(update={"value": 4})]})
    assert evaluate(history, impossible)["rows"] == []
    assert [row["ticker"] for row in evaluate(history,
        impossible.model_copy(update={"range_mode": "any"}))["rows"]] == ["FULL"]
    low = Screen(range_levels=[{"metric": "above_low_pct", "operator": "at_least", "value": 20}])
    assert [row["ticker"] for row in evaluate(history, low)["rows"]] == ["FULL"]
    with pytest.raises(ValidationError):
        Screen(range_levels=[{"metric": "below_high_pct", "operator": "at_most", "value": 1}] * 9)


def test_crossing_uses_market_sessions_and_equality():
    # A market holiday separates Thursday and Monday.
    dates = pd.to_datetime(["2026-04-02", "2026-04-06", "2026-04-07"])
    diff = pd.DataFrame(
        {"UP": [0, 1, 2], "DOWN": [0, -2, -3], "MISSING": [np.nan, 1, 2]}, index=dates
    )
    states, matches = signal(diff, 1, "cross_up")
    assert states["UP"] == "up" and states["DOWN"] == "down" and pd.isna(states["MISSING"])
    assert matches.to_dict() == {"UP": True, "DOWN": False, "MISSING": False}
    assert not signal(diff, 0, "cross_up")[1].any()
    assert signal(diff, 1, "cross_down")[1]["DOWN"]


def test_universe_filters_intersect_before_technical_filters():
    history = fixture_history()
    history.groups = {"NIFTY50": {"FULL", "OUTSIDE"}, "NIFTY100": {"FULL"},
                      "NIFTYSMALLCAP250": {"IPO"}, "NSE_FO": {"FULL"}}
    history.industries = {"FULL": "Banks", "IPO": "Energy"}
    full = evaluate(history, Screen(index_code="NIFTY50", cap="large", industry="Banks",
                                    fo_only=True, below_high_pct=5))
    assert (full["members"], full["priced"], full["range_coverage"]) == (1, 1, 1)
    assert [(r["ticker"], r["cap"], r["industry"]) for r in full["rows"]] == [("FULL", "large", "Banks")]
    assert full["industries"] == ["Banks", "Energy"]
    assert evaluate(history, Screen(index_code="NIFTY50", cap="small"))["members"] == 0
    small = evaluate(history, Screen(cap="small", below_high_pct=5))
    assert small["members"] == 1 and small["rows"] == []
    with pytest.raises(ValidationError):
        Screen(index_code="unrecognized")


def test_custom_macd_and_warmup():
    data = pd.DataFrame({"a": [10.0, 10.0, 10.0, 12.0, 8.0, 15.0]})
    macd = ema(data, 2) - ema(data, 3)
    assert np.isnan(macd.a.iloc[1])
    assert macd.a.iloc[3] == pytest.approx(1 / 3)
    assert (macd - ema(macd, 2)).a.iloc[3] == pytest.approx(1 / 9)
    assert signal(macd - ema(macd, 2), 1, "cross_down")[1]["a"]


@pytest.mark.parametrize(
    "args",
    [
        {"ema_fast": 21},
        {"macd_fast": 27},
        {"below_high_pct": -1},
        {"ema_sessions_ago": -1},
        {"macd_signal": 101},
    ],
)
def test_invalid_rules(args):
    with pytest.raises(ValidationError):
        Screen(**args)


def test_stock_indicator_periods_match_screen_and_work_for_directory_only_name(monkeypatch):
    from stock_agents.api import screener

    history = fixture_history()
    query = Screen(ema_fast=7, ema_slow=18, macd_signal=5, ema_sessions_ago=1)
    expected = evaluate(history, query)
    periods = screener.IndicatorPeriods(**query.model_dump(include=set(screener.IndicatorPeriods.model_fields)))
    monkeypatch.setattr(screener, "cached_history", lambda: history)
    actual = screener.stock_indicators("full", periods, None)
    assert actual["values"] == expected["rows"][0]
    assert actual["matches_filters"] is True
    assert actual["ema_date"] == expected["ema_date"]
    outside = screener.stock_indicators("full", query.model_copy(update={"below_high_pct": 0}), None)
    assert outside["values"] == actual["values"]
    assert outside["matches_filters"] is False
    history.members = history.members[:1]
    assert screener.stock_indicators("IPO", periods, None)["values"]["high_52w"] is None
    assert evaluate(history, query)["members"] == 1


@pytest.mark.parametrize("field,close,limit", [
    ("below_high_pct", 95, 5), ("above_high_pct", 105, 5),
    ("below_low_pct", 71.25, 5), ("above_low_pct", 78.75, 5),
])
def test_four_range_directions_use_prior_window_and_inclusive_limits(field, close, limit):
    history = fixture_history()
    history.close.iloc[-1, 0] = close
    history.raw.iloc[-1, 0] = close * 2
    # Today's intraday extremes must not swallow a breakout of the preceding range.
    history.high.iloc[-1, 0] = max(close, 100) + 1
    history.low.iloc[-1, 0] = min(close, 75) - 1
    rows = evaluate(history, Screen(**{field: limit}))["rows"]
    assert [row["ticker"] for row in rows] == ["FULL"]
    assert rows[0][field] == limit
    assert (rows[0]["high_52w"], rows[0]["low_52w"]) == (200, 150)
    assert evaluate(history, Screen(**{field: limit - 0.01}))["rows"] == []


def test_range_directions_exclude_the_opposite_side_and_combine():
    history = fixture_history()
    assert evaluate(history, Screen(above_high_pct=10))["rows"] == []
    assert evaluate(history, Screen(below_low_pct=10))["rows"] == []
    assert [row["ticker"] for row in evaluate(history, Screen(
        below_high_pct=5, above_low_pct=27))["rows"]] == ["FULL"]
    assert evaluate(history, Screen(below_high_pct=5, above_low_pct=25))["rows"] == []


def test_heikin_ashi_uses_ohlc_average_and_recursive_open():
    from stock_agents.api import screener

    dates = pd.bdate_range("2026-01-01", periods=3)
    opening = pd.DataFrame({"A": [8., 9., 10.]}, index=dates)
    close = opening + 2
    ha_open, ha_close = screener.heikin_ashi(opening, opening + 4, opening - 2, close)
    assert ha_open.A.tolist() == [9., 9., 9.5]
    assert ha_close.A.tolist() == [9., 10., 11.]


def candle_history():
    dates = pd.bdate_range("2024-01-01", periods=300)
    close = pd.DataFrame(100., index=dates,
                         columns=["UP", "DOWN", "GREEN", "DOJI", "MISSING", "GAP", "IPO"])
    close.iloc[-2] = [80, 120, 120, 80, 80, np.nan, np.nan]
    close.iloc[-1] = [120, 80, 130, 90, 120, 120, 120]
    close.loc[dates[:-1], "IPO"] = np.nan
    opening = close.copy()
    opening.iloc[-1, opening.columns.get_loc("MISSING")] = np.nan
    return History(close.columns, close, close + 1, close - 1, close * 2, open=opening)


@pytest.mark.parametrize("rule,ticker,event,color", [
    ("red_to_green", "UP", "red_to_green", "green"),
    ("green_to_red", "DOWN", "green_to_red", "red"),
])
def test_heikin_ashi_filters_only_latest_strict_color_reversals(rule, ticker, event, color):
    from stock_agents.api.screener import ScreenResult

    result = evaluate(candle_history(), Screen(heikin_ashi_rule=rule))
    rows = ScreenResult.model_validate(result).rows
    assert [row.ticker for row in rows] == [ticker]
    assert rows[0].heikin_ashi_transition == event
    assert rows[0].heikin_ashi_color == color
    assert rows[0].heikin_ashi_open == (180 if ticker == "UP" else 220)


def test_heikin_ashi_any_keeps_missing_history_and_composes_with_range(monkeypatch):
    from stock_agents.api import screener

    history = candle_history()
    rows = {row["ticker"]: row for row in evaluate(history, Screen())["rows"]}
    assert len(rows) == 7
    assert rows["DOJI"]["heikin_ashi_color"] == "doji"
    assert rows["DOJI"]["heikin_ashi_transition"] == "none"
    assert rows["MISSING"]["heikin_ashi_color"] is None
    assert rows["GAP"]["heikin_ashi_transition"] is None
    assert rows["IPO"]["heikin_ashi_transition"] is None
    assert evaluate(history, Screen(heikin_ashi_rule="red_to_green", below_high_pct=5))["rows"] == []
    monkeypatch.setattr(screener, "cached_history", lambda: history)
    result = screener.stock_indicators("UP", Screen(heikin_ashi_rule="green_to_red", below_low_pct=5), None)
    assert result["values"]["ticker"] == "UP"
    assert result["matches_filters"] is False


@pytest.mark.parametrize("args", [
    {"above_high_pct": -1}, {"below_low_pct": 101}, {"above_high_pct": float("inf")},
    {"heikin_ashi_rule": "green"},
])
def test_new_screen_filter_validation(args):
    with pytest.raises(ValidationError):
        Screen(**args)


def test_detail_preserves_values_when_screen_universe_excludes_stock(monkeypatch):
    from stock_agents.api import screener

    history = fixture_history()
    history.members = history.members[:1]
    monkeypatch.setattr(screener, "cached_history", lambda: history)
    detail = screener.stock_indicators("IPO", Screen(screen_universe=True), None)
    assert detail["values"]["ticker"] == "IPO"
    assert not detail["matches_filters"]
    detail = screener.stock_indicators("FULL", Screen(industry="Banks", screen_universe=True), None)
    assert detail["values"]["ticker"] == "FULL"
    assert not detail["matches_filters"]


def test_broker_indicator_price_keeps_each_tickers_last_verified_price_basis():
    from stock_agents.common.price_basis import indicator_closes

    bars = pd.DataFrame([
        ("A", 2, 104, None, "angel_one"), ("B", 1, 30, None, "angel_one"),
        ("A", 1, 100, 50, "eodhd"), ("C", 1, 60, None, "nse_bhavcopy"),
    ], columns=["ticker", "date", "close", "adj_close", "source"])
    observed = indicator_closes(bars)
    assert observed.iloc[:3].tolist() == [52, 30, 50]
    assert pd.isna(observed.iloc[3])
