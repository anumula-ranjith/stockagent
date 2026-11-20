"""Combine the four agent scores into a long/short book."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from stock_agents.common import config as _config
from stock_agents.storage.warehouse import Warehouse


def combine_latest(
    conn: Warehouse,
    asof: str | None = None,
    n_per_side: int = 10,
    mode: str = "weighted",
) -> dict[str, Any]:
    if asof:
        asof_date = date.fromisoformat(asof)
    else:
        r = conn.execute("SELECT MAX(date) FROM agent_scores").fetchone()
        asof_date = r[0] if r and r[0] else date.today()

    scores = conn.execute(
        "SELECT ticker, agent, score FROM agent_scores WHERE date = ?", [asof_date]
    ).fetchall()
    cls = conn.execute(
        """SELECT ticker, sector FROM classification
           WHERE effective_date = (SELECT MAX(effective_date) FROM classification cl2
                                   WHERE cl2.ticker = classification.ticker)"""
    ).fetchall()
    return rank_scores(scores, cls, asof_date, n_per_side, mode)


def rank_scores(
    rows: list[tuple[str, str, float | None]],
    classifications: list[tuple[str, str | None]],
    asof_date: date,
    n_per_side: int,
    mode: str,
    *,
    custom_weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    settings = _config.load_settings()
    combiner = settings.weights.get("combiner", {})
    configured = combiner.get("agent_weights", {})
    aliases = {"technical": "tech", "sentiment": "sent", "momentum": "mom", "fundamental": "fund"}
    weights = {
        agent: (custom_weights or {}).get(agent, configured.get(agent, configured.get(key, 25)))
        for agent, key in aliases.items()
    }
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("Set at least one weight above zero")
    weights = {agent: value / total for agent, value in weights.items()}
    if not rows:
        return {"asof": str(asof_date), "longs": [], "shorts": [], "note": "no scores yet"}

    frame = pd.DataFrame(rows, columns=["ticker", "agent", "score"])
    scores = frame.pivot(index="ticker", columns="agent", values="score").reset_index()
    scores = scores.merge(
        pd.DataFrame(classifications, columns=["ticker", "sector"]), on="ticker", how="left"
    )

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

    max_per_sector = combiner.get("max_names_per_sector", 3)

    def pick(df: pd.DataFrame, ascending: bool, n: int) -> list[dict[str, Any]]:
        df = df.sort_values("composite", ascending=ascending)
        sector_counts: dict[str, int] = {}
        out = []
        for row in df.itertuples():
            sec = "Unknown" if pd.isna(row.sector) else row.sector
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
