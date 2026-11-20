"""Replay the ranker's settings on observed membership and point-in-time signals."""

from datetime import date, timedelta
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from stock_agents.engine.ranker import RankSettings, feature, score_book
from stock_agents.engine.ranker_inputs import PUBLIC_SOURCE, snapshot_inputs


class Replay(BaseModel):
    settings: RankSettings = Field(default_factory=RankSettings)
    end: date
    months: Literal[3, 6, 12, 24, 36] = 12
    rebalance: Literal["weekly", "monthly"] = "monthly"
    portfolio: Literal["long_short", "long_only", "130_30"] = "long_short"
    universe: Literal["historical", "current_cohort"] = "historical"
    weighting: Literal["equal", "score", "inverse_vol"] = "equal"
    cost_bps: float = Field(10, ge=0, le=200, allow_inf_nan=False)


def _metrics(level):
    r = level.pct_change().dropna()
    ann = (level.iloc[-1] / level.iloc[0]) ** (252 / max(len(r), 1)) - 1
    vol = r.std(ddof=0) * np.sqrt(252)
    downside = np.sqrt(np.mean(r.clip(upper=0) ** 2)) * np.sqrt(252)
    dd = (level / level.cummax() - 1).min()
    mean = r.mean() * 252
    return {
        "annual_return": float(ann),
        "total_return": float(level.iloc[-1] / level.iloc[0] - 1),
        "annual_vol": float(vol),
        "max_drawdown": float(dd),
        "sharpe": float(mean / vol) if vol else 0.0,
        "sortino": float(mean / downside) if downside else None,
        "calmar": float(ann / -dd) if dd else None,
        "up_days": float((r > 0).mean()),
    }


def _targets(frame, book, cfg, traded):
    result = pd.Series(0.0, index=traded)
    long_exposure, short_exposure = {
        "long_short": (0.5, -0.5),
        "long_only": (1.0, 0),
        "130_30": (1.3, -0.3),
    }[cfg.portfolio]
    for side, exposure in [("longs", long_exposure), ("shorts", short_exposure)]:
        names = [t for t in book[side] if t in result.index]
        if not names or not exposure:
            continue
        if cfg.weighting == "inverse_vol":
            vol = feature(frame.loc[names], "volatility")
            weights = 1 / vol.where(vol > 0)
        elif cfg.weighting == "score":
            scores = frame.loc[names, "composite"]
            weights = scores if side == "longs" else 100 - scores
        else:
            weights = pd.Series(1.0, index=names)
        if weights.sum() > 0:
            result.loc[names] = weights.fillna(0) / weights.sum() * exposure
    return result


def replay(conn, cfg: Replay):
    end = cfg.end
    start = (pd.Timestamp(end) - pd.DateOffset(months=cfg.months)).date()
    knowledge_filter = "AND known_date<=date" if cfg.universe == "historical" else ""
    rows = conn.execute(
        f"""SELECT date,ticker,adj_close FROM (
      SELECT p.*,ROW_NUMBER() OVER (PARTITION BY date,ticker ORDER BY
          CASE WHEN source='eodhd' THEN 0 ELSE 1 END,source) rn FROM prices_daily p
      WHERE date BETWEEN ? AND ? AND known_date<=? AND adj_close>0 AND volume>0 {knowledge_filter} AND {PUBLIC_SOURCE}
        AND EXISTS (SELECT 1 FROM index_membership m WHERE m.ticker=p.ticker AND m.index_code='NIFTY500')
      ) q WHERE rn=1""",
        [start - timedelta(days=10), end, end],
    ).fetchall()
    if not rows:
        return {"error": "No adjusted Nifty 500 price history is available for this period."}
    prices = (
        pd.DataFrame.from_records(rows, columns=["date", "ticker", "price"])
        .pivot(index="date", columns="ticker", values="price")
        .sort_index()
    )
    prices = prices.loc[start:end]
    if len(prices) < 3:
        return {
            "error": "At least three closing sessions are needed for signal, execution and return."
        }
    # Parse dated membership for the benchmark too. The first recorded cohort
    # cannot be projected back into earlier periods.
    membership = conn.execute(
        """SELECT ticker,joined_on,left_on,known_on FROM index_membership
        WHERE index_code='NIFTY500' AND known_on<=? AND joined_on<=? AND (left_on IS NULL OR left_on>=?)""",
        [end, end, start],
    ).fetchall()
    retrospective = cfg.universe == "current_cohort"
    if retrospective:
        membership = [row for row in membership if row[2] is None or row[2] > end]
    if not membership or (
        not retrospective and min(max(j, k) for _, j, _, k in membership) >= prices.index[-2]
    ):
        return {
            "error": "No earlier point-in-time Nifty 500 membership is stored for this period. A replay needs membership before its first trade."
        }
    dates = prices.index.tolist()
    target_by_day = {}
    current_period = None
    last_book = {"longs": [], "shorts": []}
    target_scores = {}
    for i, day in enumerate(dates[:-2]):
        period = day.isocalendar()[:2] if cfg.rebalance == "weekly" else (day.year, day.month)
        if period == current_period:
            continue
        raw, _ = snapshot_inputs(conn, day, cohort_date=end if retrospective else None)
        if raw.empty:
            continue
        current_period = period
        ranked, books = score_book(raw, cfg.settings)
        book = books["combined"]
        execution = dates[i + 1]
        tradable = prices.loc[execution].dropna().index
        target = _targets(ranked, book, cfg, tradable).reindex(prices.columns, fill_value=0.0)
        target_by_day[execution] = target
        target_scores[execution] = ranked["composite"].to_dict()
        last_book = {
            "longs": target[target > 0].index.tolist(),
            "shorts": target[target < 0].index.tolist(),
        }
    invested = [day for day, w in target_by_day.items() if w.abs().sum() > 0]
    if not invested:
        return {
            "error": "No eligible positions had point-in-time signals and a subsequent execution price. Check the filters and historical data coverage."
        }
    first = dates.index(invested[0]) - 1
    days = dates[first:]
    levels, bench = [1.0], [1.0]
    weights = pd.Series(0.0, index=prices.columns)
    changes = []
    trade_log = []
    last_holdings = []
    last_rebalance = None
    # Retain the last mark across a missing quote and realize the move when trading resumes.
    returns = prices.ffill().pct_change(fill_method=None).fillna(0.0)
    benchmark_weights = pd.Series(0.0, index=prices.columns)
    for prior, day in zip(days, days[1:], strict=False):
        daily = returns.loc[day]
        membership_prior = {
            ticker
            for ticker, joined, left, known in membership
            if retrospective
            or (joined <= prior and known <= prior and (left is None or left > prior))
        }
        benchmark_names = prices.loc[prior].dropna().index.intersection(membership_prior)
        benchmark_weights[:] = 0.0
        if len(benchmark_names):
            benchmark_weights.loc[benchmark_names] = 1 / len(benchmark_names)
        bench.append(bench[-1] * (1 + benchmark_weights.dot(daily)))
        move = weights.dot(daily) - max(0.0, -weights.clip(upper=0).sum()) * 0.005 / 252
        if move <= -1:
            return {
                "error": "The simulated portfolio lost its capital during the requested period."
            }
        drift = weights * (1 + daily) / (1 + move)
        cost = 0.0
        if day in target_by_day:
            target = target_by_day[day]
            turnover = float((target - drift).abs().sum())
            changes.append(turnover)
            cost = turnover * cfg.cost_bps / 10000
            scores = target_scores[day]
            for ticker in target.index[(target - drift).abs() > 1e-9]:
                previous, next_weight = float(drift[ticker]), float(target[ticker])
                if previous > 0 and next_weight < 0:
                    actions = ("Sell", "Short")
                elif previous < 0 and next_weight > 0:
                    actions = ("Cover", "Buy")
                elif previous >= 0 and next_weight > previous:
                    action = "Buy"
                    actions = (action,)
                elif previous > 0 and next_weight <= 0:
                    action = "Sell"
                    actions = (action,)
                elif previous <= 0 and next_weight < previous:
                    action = "Short"
                    actions = (action,)
                else:
                    action = "Cover"
                    actions = (action,)
                score = scores.get(ticker)
                for action in actions:
                    trade_log.append({"date": str(day), "ticker": ticker, "action": action,
                                      "composite": round(float(score), 1) if pd.notna(score) else None})
            last_holdings = sorted(({
                "ticker": ticker, "side": "Long" if weight > 0 else "Short",
                "weight": round(float(weight), 6),
                "composite": round(float(scores[ticker]), 1) if pd.notna(scores.get(ticker)) else None,
            } for ticker, weight in target.items() if abs(weight) > 1e-9),
                key=lambda holding: (holding["side"] == "Short", -abs(holding["weight"]),
                                     holding["ticker"]))
            last_rebalance = str(day)
            drift = target
        levels.append(levels[-1] * (1 + move) * (1 - cost))
        weights = drift
    strategy, benchmark = pd.Series(levels, index=days), pd.Series(bench, index=days)
    perf, benchmark_perf = _metrics(strategy), _metrics(benchmark)
    sr, br = strategy.pct_change().dropna(), benchmark.pct_change().dropna()
    variance = br.var()
    return {
        **perf,
        "benchmark": benchmark_perf,
        "start": str(days[0]),
        "end": str(days[-1]),
        "requested_start": str(start),
        "requested_end": str(end),
        "n_days": len(days),
        "n_per_side": cfg.settings.size,
        "rebalance": cfg.rebalance,
        "turnover": float(np.mean(changes)),
        "beta": float(sr.cov(br) / variance) if variance > 0 else None,
        "rebalances": len(changes),
        "longs_last": last_book["longs"],
        "shorts_last": last_book["shorts"],
        "holdings_last": last_holdings,
        "holdings_date": last_rebalance,
        "trades_latest": list(reversed(trade_log[-40:])),
        "settings": cfg.model_dump(mode="json"),
        "equity_curve": [
            {
                "date": str(d),
                "equity": round(float(v), 6),
                "benchmark": round(float(benchmark.loc[d]), 6),
            }
            for d, v in strategy.items()
        ],
    }
