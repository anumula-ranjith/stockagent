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
