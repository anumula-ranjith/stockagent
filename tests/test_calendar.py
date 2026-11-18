import pandas as pd
import pytest

from stock_agents.common.calendar import rebalance_dates


def _days():
    return pd.date_range("2024-01-02", "2024-03-29", freq="B")


def test_daily_returns_all():
    out = rebalance_dates(_days(), "daily")
    assert len(out) == len(_days())


def test_weekly_one_per_week():
    out = rebalance_dates(_days(), "weekly")
    # Jan 2 - Mar 29 is ~13 weeks.
    assert 12 <= len(out) <= 14
    assert all(isinstance(x, pd.Timestamp) for x in out)


def test_monthly_three_months():
    out = rebalance_dates(_days(), "monthly")
    assert len(out) == 3


def test_unknown_cadence_raises():
    with pytest.raises(ValueError):
        rebalance_dates(_days(), "fortnightly")
