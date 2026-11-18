"""Score computation and persistence.

Each agent produces a 0–100 score per ticker, stored in `agent_scores`.
The combiner (engine/combiner.py) then merges them into longs/shorts.

Scoring rule (simple, auditable):
  - Percentile-rank each factor cross-sectionally (0..1), direction-adjusted.
  - Mean the ranks per agent → scale to 0..100.
  - Missing data → neutral 50 (imputed=true in agent_scores).
"""

from __future__ import annotations

from datetime import date
from typing import Any

import duckdb
import pandas as pd

from stock_agents.common import config as _config
from stock_agents.common.logging import get_logger
from stock_agents.factors.technical import compute_technical_factors

log = get_logger(__name__)


def _winsorize_rank(s: pd.Series) -> pd.Series:
    """Cross-sectional percentile rank in [0,1]; NaN stays NaN."""
    return s.rank(pct=True)


# ---------------------------------------------------------------- Technical
def technical_scores(conn: duckdb.DuckDBPyConnection, asof: date) -> pd.DataFrame:
    """Return DataFrame[ticker, score, imputed]."""
    f = compute_technical_factors(conn, asof)
    if f.empty:
        return pd.DataFrame(columns=["ticker", "score", "imputed"])
    # Direction: higher = better for returns, lower = better for vol.
    # Use closeness to 50 for RSI (mean-reversion is weak; momentum RSI > 50 bullish).
    ranks = pd.DataFrame(index=f.index)
    ranks["ret_1m"] = _winsorize_rank(f["ret_1m"])
    ranks["ret_3m"] = _winsorize_rank(f["ret_3m"])
    ranks["ret_6m"] = _winsorize_rank(f["ret_6m"])
    ranks["ret_12m"] = _winsorize_rank(f["ret_12m"])
    ranks["vol_60d"] = 1 - _winsorize_rank(f["vol_60d"])
    ranks["ma_dist_50"] = _winsorize_rank(f["ma_dist_50"])
    ranks["ma_dist_200"] = _winsorize_rank(f["ma_dist_200"])
    ranks["rsi_14"] = _winsorize_rank(f["rsi_14"].fillna(50))
    mean_rank = ranks.mean(axis=1, skipna=True)
    imputed = mean_rank.isna()
    score = (mean_rank.fillna(0.5) * 100).round(2)
    return pd.DataFrame(
        {"ticker": f.index, "score": score.values, "imputed": imputed.values}
    ).reset_index(drop=True)


# ----------------------------------------------------------------- Momentum
def momentum_scores(conn: duckdb.DuckDBPyConnection, asof: date) -> pd.DataFrame:
    f = compute_technical_factors(conn, asof)
    if f.empty:
        return pd.DataFrame(columns=["ticker", "score", "imputed"])
    # Classic 12-1 momentum, plus 3M and 6M. Higher = stronger.
    mom12_1 = f["ret_12m"] - f["ret_1m"]
    ranks = pd.concat(
        [
            _winsorize_rank(mom12_1).rename("mom_12_1"),
            _winsorize_rank(f["ret_3m"]).rename("ret_3m"),
            _winsorize_rank(f["ret_6m"]).rename("ret_6m"),
        ],
        axis=1,
    )
    mean_rank = ranks.mean(axis=1, skipna=True)
    imputed = mean_rank.isna()
    score = (mean_rank.fillna(0.5) * 100).round(2)
    return pd.DataFrame(
        {"ticker": f.index, "score": score.values, "imputed": imputed.values}
    ).reset_index(drop=True)


# ---------------------------------------------------------------- Sentiment
def sentiment_scores(conn: duckdb.DuckDBPyConnection, asof: date) -> pd.DataFrame:
    rows = conn.execute(
        """SELECT ticker,
                  AVG(polarity) AS pol,
                  SUM(n_headlines) AS hn
           FROM sentiment_daily
           WHERE effective_date >= ? - INTERVAL '30 days'
             AND effective_date <= ?
             AND known_date <= ?
           GROUP BY ticker""",
        [asof, asof, asof],
    ).fetchall()
    if not rows:
        all_t = conn.execute("SELECT ticker FROM symbology WHERE active = TRUE").fetchall()
        return pd.DataFrame({"ticker": [t[0] for t in all_t], "score": 50.0, "imputed": True})
    df = pd.DataFrame(rows, columns=["ticker", "pol", "hn"])
    df["rank_pol"] = _winsorize_rank(df["pol"])
    df["rank_vol"] = _winsorize_rank(df["hn"])
    mr = df[["rank_pol", "rank_vol"]].mean(axis=1, skipna=True)
    df["imputed"] = mr.isna() | (df["hn"] < 3)
    df["score"] = (mr.fillna(0.5) * 100).round(2)
    # If headline count is below threshold, mark imputed but keep score
    all_t = [r[0] for r in conn.execute("SELECT ticker FROM symbology WHERE active = TRUE").fetchall()]
    out = pd.DataFrame({"ticker": all_t})
    out = out.merge(df[["ticker", "score", "imputed"]], on="ticker", how="left")
    out["score"] = out["score"].fillna(50.0)
    out["imputed"] = out["imputed"].fillna(True)
    return out


# -------------------------------------------------------------- Fundamental
def fundamental_scores(conn: duckdb.DuckDBPyConnection, asof: date) -> pd.DataFrame:
    """Placeholder: fundamentals pipeline is Phase 3+ (requires parsing the
    fundamentals JSON from EODHD). Until then: all neutral 50, flagged imputed.
    """
    all_t = [r[0] for r in conn.execute("SELECT ticker FROM symbology WHERE active = TRUE").fetchall()]
    return pd.DataFrame({"ticker": all_t, "score": 50.0, "imputed": True})


AGENTS = {
    "technical": technical_scores,
    "momentum": momentum_scores,
    "sentiment": sentiment_scores,
    "fundamental": fundamental_scores,
}


def compute_and_store(conn: duckdb.DuckDBPyConnection, asof: date | None = None) -> dict[str, int]:
    """Compute scores for all 4 agents as of `asof` and INSERT into agent_scores."""
    asof = asof or date.today()
    today = date.today()
    counts: dict[str, int] = {}
    for name, fn in AGENTS.items():
        try:
            df = fn(conn, asof)
        except Exception as e:
            log.exception("agent %s failed: %s", name, e)
            continue
        if df.empty:
            counts[name] = 0
            continue
        rows = [
            (asof, r.ticker, name, float(r.score), not bool(r.imputed))
            for r in df.itertuples()
        ]
        conn.executemany(
            """INSERT OR REPLACE INTO agent_scores
               (date, ticker, agent, score, passes)
               VALUES (?,?,?,?,?)""",
            rows,
        )
        counts[name] = len(rows)
        log.info("%s scores: %d rows", name, len(rows))
    return counts


def latest_agent_scores(
    conn: duckdb.DuckDBPyConnection, name: str, asof: str | None = None
) -> list[dict[str, Any]]:
    """Read back persisted scores for one agent, latest asof."""
    if asof:
        asof_date = date.fromisoformat(asof)
    else:
        row = conn.execute(
            "SELECT MAX(date) FROM agent_scores WHERE agent = ?", [name]
        ).fetchone()
        asof_date = row[0] if row and row[0] else date.today()
    rows = conn.execute(
        """SELECT s.ticker, s.score, s.passes, cl.sector, cl.industry
           FROM agent_scores s
           LEFT JOIN classification cl ON cl.ticker = s.ticker
           WHERE s.agent = ? AND s.date = ?
           ORDER BY s.score DESC""",
        [name, asof_date],
    ).fetchall()
    return [
        {"ticker": t, "score": sc, "imputed": not bool(p), "sector": sec, "industry": ind}
        for t, sc, p, sec, ind in rows
    ]
