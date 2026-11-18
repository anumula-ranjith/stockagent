"""Technical factors computed from the prices_daily table.

All factors return a pandas Series indexed by ticker, with the factor value
computed as of `asof` (or the latest known date). Missing data → NaN; the
agent layer imputes to the neutral score (50).
"""

from __future__ import annotations

from datetime import date, timedelta

import duckdb
import pandas as pd


def _prices_pivot(
    conn: duckdb.DuckDBPyConnection, asof: date, lookback_days: int = 400
) -> pd.DataFrame:
    """Return wide DataFrame: index=date, columns=ticker, values=adj_close.

    Only rows with known_date <= asof (PIT discipline).
    """
    cutoff = asof - timedelta(days=lookback_days)
    rows = conn.execute(
        """SELECT date, ticker, adj_close
           FROM prices_daily
           WHERE date BETWEEN ? AND ?
             AND known_date <= ?
             AND adj_close IS NOT NULL
           ORDER BY date""",
        [cutoff, asof, asof],
    ).fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["date", "ticker", "adj_close"])
    return df.pivot(index="date", columns="ticker", values="adj_close").sort_index()


def returns(prices: pd.DataFrame, window_days: int) -> pd.Series:
    """Simple return over window_days (latest close / close N bars ago - 1)."""
    if prices.empty or len(prices) < window_days + 1:
        return pd.Series(dtype=float)
    return (prices.iloc[-1] / prices.iloc[-window_days - 1] - 1).rename(f"ret_{window_days}d")


def volatility(prices: pd.DataFrame, window_days: int = 60) -> pd.Series:
    """Annualized vol of daily log returns over window_days."""
    if prices.empty or len(prices) < window_days + 1:
        return pd.Series(dtype=float)
    pct = prices.pct_change().iloc[-window_days:]
    return (pct.std() * (252**0.5)).rename("vol_60d")


def rsi(prices: pd.DataFrame, window: int = 14) -> pd.Series:
    """Simple RSI on the final window."""
    if prices.empty or len(prices) < window + 1:
        return pd.Series(dtype=float)
    delta = prices.diff()
    gains = delta.clip(lower=0).rolling(window).mean()
    losses = (-delta.clip(upper=0)).rolling(window).mean()
    rs = gains / losses.replace(0, 1e-12)
    rsi_series = (100 - 100 / (1 + rs)).iloc[-1]
    return rsi_series.rename("rsi_14")


def ma_distance(prices: pd.DataFrame, window: int = 50) -> pd.Series:
    """(price - MA) / MA, latest observation."""
    if prices.empty or len(prices) < window + 1:
        return pd.Series(dtype=float)
    ma = prices.rolling(window).mean().iloc[-1]
    return (prices.iloc[-1] / ma - 1).rename(f"ma_dist_{window}")


def compute_technical_factors(
    conn: duckdb.DuckDBPyConnection, asof: date | None = None
) -> pd.DataFrame:
    """One row per ticker, columns = factor values."""
    asof = asof or date.today()
    px = _prices_pivot(conn, asof)
    if px.empty:
        return pd.DataFrame()
    out = pd.concat(
        [
            returns(px, 21).rename("ret_1m"),
            returns(px, 63).rename("ret_3m"),
            returns(px, 126).rename("ret_6m"),
            returns(px, 252).rename("ret_12m"),
            volatility(px, 60),
            rsi(px, 14),
            ma_distance(px, 50),
            ma_distance(px, 200),
        ],
        axis=1,
    )
    out.index.name = "ticker"
    return out
