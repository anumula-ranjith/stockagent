"""Combine the four agent scores into a long/short book."""

from __future__ import annotations

from datetime import date
from typing import Any

import duckdb
import pandas as pd

from stock_agents.common import config as _config


def _load_scores(conn: duckdb.DuckDBPyConnection, asof: date) -> pd.DataFrame:
    rows = conn.execute(
        """SELECT ticker, agent, score, passes
           FROM agent_scores
           WHERE date = ?""",
        [asof],
    ).fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["ticker", "agent", "score", "passes"])
    return df.pivot(index="ticker", columns="agent", values="score").reset_index()


def combine_latest(
    conn: duckdb.DuckDBPyConnection,
    asof: str | None = None,
    n_per_side: int = 10,
    mode: str = "weighted",
) -> dict[str, Any]:
    if asof:
        asof_date = date.fromisoformat(asof)
    else:
        r = conn.execute("SELECT MAX(date) FROM agent_scores").fetchone()
        asof_date = r[0] if r and r[0] else date.today()

    scores = _load_scores(conn, asof_date)
    if scores.empty:
        return {"asof": str(asof_date), "longs": [], "shorts": [], "note": "no scores yet"}

    # Attach sector for sector cap
    cls = conn.execute(
        """SELECT ticker, sector FROM classification
           WHERE effective_date = (SELECT MAX(effective_date) FROM classification cl2
                                   WHERE cl2.ticker = classification.ticker)"""
    ).fetchall()
    scores = scores.merge(
        pd.DataFrame(cls, columns=["ticker", "sector"]), on="ticker", how="left"
    )

    settings = _config.load_settings()
    w = settings.weights.get("combiner", {}).get("agent_weights", {})
    weights = {
        "technical": w.get("tech", 25) / 100.0,
        "sentiment": w.get("sent", 25) / 100.0,
        "momentum": w.get("mom", 25) / 100.0,
        "fundamental": w.get("fund", 25) / 100.0,
    }

    for a in ("technical", "sentiment", "momentum", "fundamental"):
        if a not in scores.columns:
            scores[a] = 50.0
        scores[a] = scores[a].fillna(50.0)

    if mode == "weighted":
        scores["composite"] = sum(scores[a] * weights[a] for a in weights)
    elif mode == "consensus":
        # consensus: average of agents that agree > threshold
        thresh_long = 60
        scores["consensus_hits"] = (scores[list(weights)] > thresh_long).sum(axis=1)
        scores["composite"] = scores[list(weights)].mean(axis=1)
    else:  # hybrid
        scores["composite"] = (
            0.7 * sum(scores[a] * weights[a] for a in weights)
            + 0.3 * scores[list(weights)].min(axis=1)
        )

    max_per_sector = settings.weights.get("combiner", {}).get("max_names_per_sector", 3)

    def pick(df: pd.DataFrame, ascending: bool, n: int) -> list[dict[str, Any]]:
        df = df.sort_values("composite", ascending=ascending)
        sector_counts: dict[str, int] = {}
        out = []
        for row in df.itertuples():
            sec = row.sector or "Unknown"
            if sector_counts.get(sec, 0) >= max_per_sector:
                continue
            out.append(
                {
                    "ticker": row.ticker,
                    "sector": sec,
                    "composite": round(float(row.composite), 2),
                    "technical": round(float(row.technical), 2),
                    "sentiment": round(float(row.sentiment), 2),
                    "momentum": round(float(row.momentum), 2),
                    "fundamental": round(float(row.fundamental), 2),
                }
            )
            sector_counts[sec] = sector_counts.get(sec, 0) + 1
            if len(out) >= n:
                break
        return out

    longs = pick(scores, ascending=False, n=n_per_side)
    shorts = pick(scores, ascending=True, n=n_per_side)
    return {
        "asof": str(asof_date),
        "mode": mode,
        "weights": weights,
        "longs": longs,
        "shorts": shorts,
    }
