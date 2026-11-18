"""Nifty 500 screening against the locally ingested daily price history."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from threading import Lock
from time import monotonic
from typing import Literal

import numpy as np
import pandas as pd
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, model_validator

from stock_agents.api.auth import CurrentUser
from stock_agents.storage.warehouse import connect

router = APIRouter(tags=["screener"])
Rule = Literal["any", "above", "below", "cross_up", "cross_down"]


class Screen(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    below_high_pct: float | None = Field(None, ge=0, le=100)
    above_low_pct: float | None = Field(None, ge=0, le=10000)
    ema_fast: int = Field(9, ge=1, le=199)
    ema_slow: int = Field(21, ge=2, le=200)
    ema_rule: Rule = "any"
    ema_sessions_ago: int = Field(0, ge=0, le=20)
    macd_fast: int = Field(12, ge=1, le=199)
    macd_slow: int = Field(26, ge=2, le=200)
    macd_signal: int = Field(9, ge=1, le=100)
    macd_rule: Rule = "any"
    macd_sessions_ago: int = Field(0, ge=0, le=20)

    @model_validator(mode="after")
    def ordered_periods(self):
        if self.ema_fast >= self.ema_slow or self.macd_fast >= self.macd_slow:
            raise ValueError("Each fast period must be shorter than its slow period")
        return self


class ScreenRow(BaseModel):
    ticker: str
    close: float | None
    high_52w: float | None
    low_52w: float | None
    below_high_pct: float | None
    above_low_pct: float | None
    ema_fast: float | None
    ema_slow: float | None
    ema_cross: Literal["up", "down", "none"] | None
    macd: float | None
    macd_signal: float | None
    macd_hist: float | None
    macd_cross: Literal["up", "down", "none"] | None


class ScreenResult(BaseModel):
    asof: date | None
    ema_date: date | None
    macd_date: date | None
    members: int
    priced: int
    range_coverage: int
    rows: list[ScreenRow]


@dataclass
class History:
    members: pd.Index
    close: pd.DataFrame
    high: pd.DataFrame
    low: pd.DataFrame
    raw: pd.DataFrame


def load_history() -> History:
    today = date.today()
    with connect(read_only=True) as db:
        members = pd.Index(
            db.execute(
                """SELECT DISTINCT m.ticker FROM index_membership m JOIN symbology s USING (ticker)
               WHERE m.index_code='NIFTY500' AND m.left_on IS NULL AND s.active
                 AND m.known_on <= ? AND m.joined_on <= ? ORDER BY m.ticker""",
                [today, today],
            )
            .scalars()
            .all(),
            name="ticker",
        )
        rows = db.execute(
            """SELECT DISTINCT ON (ticker,date) ticker,date,close,high,low,adj_close
               FROM prices_daily WHERE ticker = ANY(?) AND date BETWEEN ? AND ?
                 AND known_date <= ? AND volume > 0 AND source IN ('eodhd','nse_bhavcopy')
               ORDER BY ticker,date,(adj_close IS NULL), (source='eodhd') DESC""",
            [members.tolist(), today - timedelta(days=1100), today, today],
        ).all()
    data = pd.DataFrame(rows, columns=["ticker", "date", "close", "high", "low", "adj_close"])
    data["date"] = pd.to_datetime(data["date"])

    def wide(field: str):
        frame = data.pivot(index="date", columns="ticker", values=field).reindex(columns=members)
        return frame.astype(float).where(lambda values: values.gt(0) & np.isfinite(values))

    raw, adjusted = wide("close"), wide("adj_close")
    scale = adjusted / raw
    return History(members, adjusted, wide("high") * scale, wide("low") * scale, raw)


_lock = Lock()
_cache: tuple[float, History] | None = None


def cached_history() -> History:
    global _cache
    with _lock:
        if _cache is None or monotonic() - _cache[0] >= 120:
            history = load_history()
            _cache = monotonic(), history
        return _cache[1]


def ema(values: pd.DataFrame, span: int) -> pd.DataFrame:
    return (
        values.ewm(span=span, min_periods=span, adjust=False, ignore_na=True)
        .mean()
        .where(values.notna())
    )


def signal(diff: pd.DataFrame, ago: int, rule: Rule):
    empty = pd.Series(np.nan, index=diff.columns, dtype=float)
    target = diff.iloc[-1 - ago] if len(diff) > ago else empty
    prior = diff.iloc[-2 - ago] if len(diff) > ago + 1 else empty
    up = target.gt(0) & prior.le(0)
    down = target.lt(0) & prior.ge(0)
    # Unavailable samples are never reported as an observed crossover.
    states = pd.Series(np.select([up, down], ["up", "down"], default="none"), index=diff.columns)
    states = states.where(target.notna() & prior.notna())
    matches = {"above": target.gt(0), "below": target.lt(0), "cross_up": up, "cross_down": down}
    return states, matches.get(rule, pd.Series(True, index=diff.columns))


def evaluate(h: History, q: Screen) -> dict:
    close = h.close
    dates = close.index
    asof = dates[-1] if len(dates) else None

    def session(ago: int):
        return dates[-1 - ago].date().isoformat() if len(dates) > ago else None

    result = dict(
        asof=session(0),
        members=len(h.members),
        priced=0,
        range_coverage=0,
        ema_date=session(q.ema_sessions_ago),
        macd_date=session(q.macd_sessions_ago),
        rows=[],
    )
    if asof is None:
        return result
    last = close.iloc[-1]
    cutoff = asof - pd.Timedelta(weeks=52)
    in_year = dates > cutoff
    highs, lows = h.high.loc[in_year], h.low.loc[in_year]
    # Suspensions and missing vendor sessions can interrupt otherwise seasoned listings.
    # Exclude short histories and material gaps before calculating an observed range.
    valid = highs.notna() & lows.notna()
    covered = close.loc[~in_year].notna().any() & valid.mean().ge(0.95) & last.notna()
    high, low = highs.max().where(covered), lows.min().where(covered)
    below = (1 - last / high) * 100
    above = (last / low - 1) * 100
    fast, slow = ema(close, q.ema_fast), ema(close, q.ema_slow)
    macd = ema(close, q.macd_fast) - ema(close, q.macd_slow)
    line = ema(macd, q.macd_signal)
    ema_event, ema_match = signal(fast - slow, q.ema_sessions_ago, q.ema_rule)
    macd_event, macd_match = signal(macd - line, q.macd_sessions_ago, q.macd_rule)
    selected = ema_match & macd_match
    if q.below_high_pct is not None:
        selected &= below.between(-1e-8, q.below_high_pct + 1e-8)
    if q.above_low_pct is not None:
        selected &= above.between(-1e-8, q.above_low_pct + 1e-8)
    # Express adjusted indicators in latest traded-price units.
    scale = h.raw.iloc[-1] / last
    frame = (
        pd.DataFrame(
            {
                "close": h.raw.iloc[-1],
                "high_52w": high * scale,
                "low_52w": low * scale,
                "below_high_pct": below,
                "above_low_pct": above,
                "ema_fast": fast.iloc[-1] * scale,
                "ema_slow": slow.iloc[-1] * scale,
                "ema_cross": ema_event,
                "macd": macd.iloc[-1] * scale,
                "macd_signal": line.iloc[-1] * scale,
                "macd_hist": (macd.iloc[-1] - line.iloc[-1]) * scale,
                "macd_cross": macd_event,
            }
        )
        .loc[selected]
        .round(4)
    )
    frame = frame.rename_axis("ticker").reset_index().astype(object)
    result.update(
        priced=int(last.notna().sum()),
        range_coverage=int(covered.sum()),
        rows=frame.where(frame.notna(), None).to_dict("records"),
    )
    return result


@router.post("/screener/run", response_model=ScreenResult)
def run_screen(query: Screen, _user: CurrentUser):
    return evaluate(cached_history(), query)
