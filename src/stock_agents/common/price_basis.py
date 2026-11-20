"""Extend an adjusted price series with raw Angel One session snapshots."""

import pandas as pd


def indicator_closes(bars: pd.DataFrame) -> pd.Series:
    """Return comparable indicator inputs without changing the vendor's adjusted close."""
    adjusted = bars["adj_close"].astype(float)
    broker = bars["source"].eq("angel_one") & adjusted.isna()
    if not broker.any():
        return adjusted
    ordered = bars.sort_values(["ticker", "date"])
    raw = ordered.close.astype(float)
    factor = ordered.adj_close.astype(float).div(raw.where(raw.gt(0)))
    previous_factor = factor.groupby(ordered.ticker).ffill().fillna(1.0)
    return adjusted.mask(broker, raw * previous_factor)
