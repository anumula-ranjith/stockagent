"""NYSE trading-day helpers."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from functools import lru_cache

import pandas as pd


@lru_cache(maxsize=1)
def _mcal():
    """Lazy pandas_market_calendars import so core tests don't need it loaded."""
    import pandas_market_calendars as mcal

    return mcal.get_calendar("XNYS")


def trading_days(start: str | date, end: str | date) -> pd.DatetimeIndex:
    cal = _mcal()
    sched = cal.schedule(start_date=str(start), end_date=str(end))
    return pd.DatetimeIndex(sched.index)


def next_trading_day(ts: str | date | datetime) -> pd.Timestamp:
    cal = _mcal()
    ts = pd.Timestamp(ts).normalize()
    sched = cal.schedule(
        start_date=(ts + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
        end_date=(ts + pd.Timedelta(days=10)).strftime("%Y-%m-%d"),
    )
    return pd.Timestamp(sched.index[0])


def rebalance_dates(days: Iterable[pd.Timestamp], cadence: str) -> list[pd.Timestamp]:
    """Pick one trading day per week/month, or return all days for 'daily'."""
    idx = pd.DatetimeIndex(list(days)).sort_values()
    cadence = cadence.lower()
    if cadence == "daily":
        return list(idx)
    if cadence == "weekly":
        s = pd.Series(1, index=idx)
        return list(s.groupby(idx.to_period("W")).apply(lambda x: x.index.max()))
    if cadence == "monthly":
        s = pd.Series(1, index=idx)
        return list(s.groupby(idx.to_period("M")).apply(lambda x: x.index.max()))
    raise ValueError(f"unknown cadence {cadence!r}")
