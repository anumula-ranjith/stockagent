"""Backtest engine (vectorized, monthly rebalance).

For each rebalance date in the test window:
  1. Compute agent scores from PIT data.
  2. Combine into longs/shorts (dollar-neutral).
  3. Equal-weight within each side.
  4. Carry positions until next rebalance.
Returns a summary and a per-day equity curve.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from stock_agents.common import config as _config
from stock_agents.common.logging import get_logger
from stock_agents.engine.scores import AGENTS

log = get_logger(__name__)


def _price_matrix(
    conn: duckdb.DuckDBPyConnection, start: date, end: date
) -> pd.DataFrame:
    rows = conn.execute(
        """SELECT date, ticker, adj_close
           FROM prices_daily
           WHERE date BETWEEN ? AND ? AND adj_close IS NOT NULL
           ORDER BY date""",
        [start, end],
    ).fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["date", "ticker", "adj_close"])
    return df.pivot(index="date", columns="ticker", values="adj_close").sort_index()


def run_backtest(
    conn: duckdb.DuckDBPyConnection,
    start: date,
    end: date,
    n_per_side: int = 10,
    rebalance: str = "monthly",
) -> dict[str, Any]:
    settings = _config.load_settings()
    prices = _price_matrix(conn, start, end)
    if prices.empty:
        return {"error": "no prices"}

    # rebalance dates: first trading day of each month
    rb_dates: list[pd.Timestamp] = []
    cur = pd.Timestamp(start)
    while cur <= pd.Timestamp(end):
        in_month = prices.loc[(prices.index >= cur) & (prices.index < cur + pd.offsets.MonthBegin(1))]
        if not in_month.empty:
            rb_dates.append(in_month.index[0])
        cur = (cur + pd.offsets.MonthBegin(1)).normalize()

    # For speed in this first pass: compute scores only at rebalance dates.
    equity = pd.Series(1.0, index=prices.index)
    cur_longs: list[str] = []
    cur_shorts: list[str] = []

    for i, rb in enumerate(rb_dates):
        asof = rb.date()
        # recompute scores
        techs = AGENTS["technical"](conn, asof)
        moms = AGENTS["momentum"](conn, asof)
        if techs.empty:
            continue
        composite = (
            techs.set_index("ticker")["score"].rename("tech")
            .to_frame()
            .join(moms.set_index("ticker")["score"].rename("mom"), how="outer")
        )
        composite["comp"] = composite.mean(axis=1, skipna=True)
        composite = composite.dropna(subset=["comp"]).sort_values("comp", ascending=False)
        longs = composite.head(n_per_side).index.tolist()
        shorts = composite.tail(n_per_side).index.tolist()
        cur_longs, cur_shorts = longs, shorts

        # Hold until next rebalance
        end_i = rb_dates[i + 1] if i + 1 < len(rb_dates) else prices.index[-1]
        window = prices.loc[(prices.index > rb) & (prices.index <= end_i)]
        if window.empty:
            continue
        # daily returns
        wp = prices.loc[rb:end_i]
        ret = wp.pct_change().dropna(how="all")
        if ret.empty:
            continue
        long_ret = ret[longs].mean(axis=1) if longs else 0.0
        short_ret = ret[shorts].mean(axis=1) if shorts else 0.0
        strat_ret = 0.5 * long_ret - 0.5 * short_ret
        for d, r in strat_ret.items():
            if pd.isna(r):
                continue
            equity.loc[d] = equity.loc[:d].iloc[-2] * (1 + r) if d != equity.index[0] else 1.0

    equity = equity.ffill()
    total_ret = equity.iloc[-1] - 1
    ann_ret = (1 + total_ret) ** (252 / len(equity)) - 1 if len(equity) > 0 else 0
    daily_ret = equity.pct_change().dropna()
    ann_vol = daily_ret.std() * (252 ** 0.5) if len(daily_ret) else 0.0
    sharpe = (ann_ret / ann_vol) if ann_vol else 0.0
    max_dd = (equity / equity.cummax() - 1).min()

    out_dir = settings.paths.backtests_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = date.today().isoformat()
    out_file = out_dir / f"backtest_{stamp}.json"
    summary = {
        "start": str(start),
        "end": str(end),
        "n_per_side": n_per_side,
        "rebalance": rebalance,
        "total_return": round(float(total_ret), 4),
        "annual_return": round(float(ann_ret), 4),
        "annual_vol": round(float(ann_vol), 4),
        "sharpe": round(float(sharpe), 3),
        "max_drawdown": round(float(max_dd), 4),
        "n_days": int(len(equity)),
        "longs_last": cur_longs,
        "shorts_last": cur_shorts,
        "equity_curve": [
            {"date": str(d.date() if hasattr(d, "date") else d), "equity": round(float(v), 6)}
            for d, v in equity.items()
        ],
    }
    out_file.write_text(json.dumps(summary, indent=2))
    log.info("backtest saved to %s (total_ret=%.2f%%, sharpe=%.2f)", out_file, total_ret * 100, sharpe)
    return summary


def latest_summary() -> dict[str, Any]:
    settings = _config.load_settings()
    files = sorted(settings.paths.backtests_dir.glob("backtest_*.json"))
    if not files:
        return {"note": "no backtests run yet"}
    return json.loads(files[-1].read_text())
