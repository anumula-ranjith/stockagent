"""Nifty 500 screening against the locally ingested daily price history."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from redis.exceptions import RedisError

from stock_agents.api.auth import CurrentUser
from stock_agents.common.price_basis import indicator_closes
from stock_agents.common.snapshot_cache import SnapshotCache
from stock_agents.ingest.screen_indices import CAP_INDEX, INDEX_FILES
from stock_agents.jobs.pipelines import TZ, market_calendar
from stock_agents.sources.angel_session import connection_status
from stock_agents.storage.warehouse import connect

router = APIRouter(tags=["screener"])
Rule = Literal["any", "above", "below", "cross_up", "cross_down"]
HeikinAshiRule = Literal["any", "red_to_green", "green_to_red"]


class RangeLevel(BaseModel):
    metric: Literal["below_high_pct", "above_low_pct"]
    operator: Literal["at_least", "at_most"]
    value: float = Field(ge=-10000, le=10000, allow_inf_nan=False)


class IndicatorPeriods(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    ema_fast: int = Field(9, ge=1, le=199)
    ema_slow: int = Field(21, ge=2, le=200)
    ema_sessions_ago: int = Field(0, ge=0, le=20)
    macd_fast: int = Field(12, ge=1, le=199)
    macd_slow: int = Field(26, ge=2, le=200)
    macd_signal: int = Field(9, ge=1, le=100)
    macd_sessions_ago: int = Field(0, ge=0, le=20)

    @model_validator(mode="after")
    def ordered_periods(self):
        if self.ema_fast >= self.ema_slow or self.macd_fast >= self.macd_slow:
            raise ValueError("Each fast period must be shorter than its slow period")
        return self


class Screen(IndicatorPeriods):
    screen_universe: bool = False
    index_code: str = "NIFTY500"
    cap: Literal["large", "mid", "small"] | None = None
    industry: str | None = Field(None, min_length=1, max_length=150)
    fo_only: bool = False
    below_high_pct: float | None = Field(None, ge=0, le=100)
    below_low_pct: float | None = Field(None, ge=0, le=100)
    above_high_pct: float | None = Field(None, ge=0, le=10000)
    above_low_pct: float | None = Field(None, ge=0, le=10000)
    heikin_ashi_rule: HeikinAshiRule = "any"
    range_levels: list[RangeLevel] = Field(default_factory=list, max_length=8)
    range_mode: Literal["all", "any"] = "all"
    ema_rule: Rule = "any"
    macd_rule: Rule = "any"

    @model_validator(mode="after")
    def known_index(self):
        if self.index_code != "NIFTY500" and self.index_code not in INDEX_FILES:
            raise ValueError("Unknown Nifty index")
        return self


class ScreenRow(BaseModel):
    ticker: str
    industry: str | None
    cap: str | None
    close: float | None
    high_52w: float | None
    low_52w: float | None
    below_high_pct: float | None
    above_low_pct: float | None
    below_low_pct: float | None = None
    above_high_pct: float | None = None
    heikin_ashi_open: float | None = None
    heikin_ashi_close: float | None = None
    heikin_ashi_color: Literal["green", "red", "doji"] | None = None
    heikin_ashi_transition: Literal["red_to_green", "green_to_red", "none"] | None = None
    ema_fast: float | None
    ema_slow: float | None
    ema_cross: Literal["up", "down", "none"] | None
    macd: float | None
    macd_signal: float | None
    macd_hist: float | None
    macd_cross: Literal["up", "down", "none"] | None


class ScreenResult(BaseModel):
    asof: date | None
    price_source: str | None = None
    exchange_trade_at: datetime | None = None
    ema_date: date | None
    macd_date: date | None
    members: int
    priced: int
    range_coverage: int
    index_options: dict[str, str]
    industries: list[str]
    rows: list[ScreenRow]


class StockIndicators(BaseModel):
    asof: date | None
    price_source: str | None = None
    exchange_trade_at: datetime | None = None
    ema_date: date | None
    macd_date: date | None
    values: ScreenRow | None
    matches_filters: bool


@dataclass
class History:
    members: pd.Index
    close: pd.DataFrame
    high: pd.DataFrame
    low: pd.DataFrame
    raw: pd.DataFrame
    groups: dict[str, set[str]] = field(default_factory=dict)
    industries: dict[str, str] = field(default_factory=dict)
    open: pd.DataFrame | None = None
    latest_sources: dict[str, str] = field(default_factory=dict)
    latest_trades: dict[str, datetime] = field(default_factory=dict)


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
        groups: dict[str, set[str]] = {}
        for code, ticker in db.execute(
            """SELECT index_code,ticker FROM index_membership WHERE left_on IS NULL
               AND known_on <= ? AND joined_on <= ? AND index_code = ANY(?)""",
            [today, today, [*INDEX_FILES, "NSE_FO"]],
        ):
            groups.setdefault(code, set()).add(ticker)
        industries = dict(db.execute(
            """SELECT DISTINCT ON (ticker) ticker, industry FROM classification
               WHERE ticker = ANY(?) AND source='nse_indices' AND known_date <= ?
               AND effective_date <= ? AND NULLIF(TRIM(industry),'') IS NOT NULL
               ORDER BY ticker, effective_date DESC, known_date DESC""",
            [members.tolist(), today, today],
        ).all())
        active = pd.Index(db.execute("SELECT ticker FROM symbology WHERE active").scalars().all(),
                          name="ticker")
        rows = db.execute(
            """SELECT DISTINCT ON (ticker,date) ticker,date,close,high,low,adj_close,open,
                      source,exchange_trade_at
               FROM prices_daily WHERE ticker = ANY(?) AND date BETWEEN ? AND ?
                 AND known_date <= ? AND volume > 0 AND source IN ('angel_one','eodhd','nse_bhavcopy')
               ORDER BY ticker,date,(source='angel_one') DESC,(adj_close IS NULL),(source='eodhd') DESC""",
            [active.tolist(), today - timedelta(days=1100), today, today],
        ).all()
    data = pd.DataFrame(rows, columns=["ticker", "date", "close", "high", "low", "adj_close", "open",
                                       "source", "exchange_trade_at"])
    data["date"] = pd.to_datetime(data["date"])

    def wide(field: str):
        frame = data.pivot(index="date", columns="ticker", values=field).reindex(columns=active)
        return frame.astype(float).where(lambda values: values.gt(0) & np.isfinite(values))

    data["indicator_close"] = indicator_closes(data)
    raw, adjusted = wide("close"), wide("indicator_close")
    # Keep the screener's Nifty session calendar when including directory-only names.
    sessions = data.loc[data.ticker.isin(members), "date"].unique() if len(members) else raw.index
    raw, adjusted = raw.loc[raw.index.isin(sessions)], adjusted.loc[adjusted.index.isin(sessions)]
    scale = adjusted / raw
    latest = data.loc[data.date.eq(raw.index.max())].set_index("ticker")
    return History(members, adjusted, wide("high").loc[raw.index] * scale,
                   wide("low").loc[raw.index] * scale, raw, groups, industries,
                   open=wide("open").loc[raw.index] * scale,
                   latest_sources=latest.source.to_dict(),
                   latest_trades=latest.exchange_trade_at.dropna().to_dict())


_history = SnapshotCache(capacity=1)


def cached_history() -> History:
    return _history.get("history", load_history)


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


def heikin_ashi(opening: pd.DataFrame, high: pd.DataFrame, low: pd.DataFrame,
                close: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Calculate HA bodies from adjusted OHLC, leaving missing candles unavailable."""
    valid = opening.notna() & high.notna() & low.notna() & close.notna()
    ha_close = ((opening + high + low + close) / 4).where(valid)
    values = ha_close.to_numpy()
    seeds = ((opening + close) / 2).to_numpy()
    bodies = np.full(values.shape, np.nan)
    previous_open = np.full(values.shape[1], np.nan)
    previous_close = previous_open.copy()
    for i, current in enumerate(values):
        observed = np.isfinite(current)
        current_open = np.where(np.isfinite(previous_open),
                                (previous_open + previous_close) / 2, seeds[i])
        bodies[i] = np.where(observed, current_open, np.nan)
        previous_open = np.where(observed, current_open, previous_open)
        previous_close = np.where(observed, current, previous_close)
    return pd.DataFrame(bodies, index=close.index, columns=close.columns), ha_close


def evaluate(h: History, q: Screen) -> dict:
    members = h.members
    group_codes = []
    if q.index_code != "NIFTY500":
        group_codes.append(q.index_code)
    if q.cap:
        group_codes.append(CAP_INDEX[q.cap])
    if q.fo_only:
        group_codes.append("NSE_FO")
    for code in group_codes:
        if code not in h.groups:
            raise HTTPException(503, f"Membership for {code} has not been loaded.")
        members = members[members.isin(h.groups[code])]
    if q.industry:
        members = members[members.map(h.industries.get) == q.industry]
    close = h.close[members]
    dates = close.index
    asof = dates[-1] if len(dates) else None

    def session(ago: int):
        return dates[-1 - ago].date().isoformat() if len(dates) > ago else None

    result = dict(
        asof=session(0),
        members=len(members),
        index_options={"NIFTY500": "Nifty 500", **{
            code: details[0] for code, details in INDEX_FILES.items() if code in h.groups
        }},
        industries=sorted(set(h.industries.values())),
        priced=0,
        range_coverage=0,
        ema_date=session(q.ema_sessions_ago),
        macd_date=session(q.macd_sessions_ago),
        rows=[],
    )
    sources = {h.latest_sources[t] for t in members if t in h.latest_sources}
    result["price_source"] = next(iter(sources)) if len(sources) == 1 else "mixed" if sources else None
    result["exchange_trade_at"] = max((h.latest_trades[t] for t in members if t in h.latest_trades), default=None)
    if asof is None or members.empty:
        return result
    last = close.iloc[-1]
    cutoff = asof - pd.Timedelta(weeks=52)
    # Compare the latest close with the range BEFORE that session so breakouts can match.
    in_year = (dates > cutoff) & (dates < asof)
    highs, lows = h.high.loc[in_year, members], h.low.loc[in_year, members]
    # Suspensions and missing vendor sessions can interrupt otherwise seasoned listings.
    # Exclude short histories and material gaps before calculating an observed range.
    valid = highs.notna() & lows.notna()
    covered = close.loc[dates <= cutoff].notna().any() & valid.mean().ge(0.95) & last.notna()
    high, low = highs.max().where(covered), lows.min().where(covered)
    below = (1 - last / high) * 100
    above = (last / low - 1) * 100
    above_high, below_low = -below, -above
    opening = h.open.reindex(index=dates, columns=members) if h.open is not None else close * np.nan
    ha_open, ha_close = heikin_ashi(opening, h.high[members], h.low[members], close)
    body = ha_close - ha_open
    current = body.iloc[-1]
    prior = body.iloc[-2] if len(body) > 1 else current * np.nan
    to_green = current.gt(0) & prior.lt(0)
    to_red = current.lt(0) & prior.gt(0)
    ha_color = pd.Series(np.select([current.gt(0), current.lt(0)], ["green", "red"],
                                   default="doji"), index=members).where(current.notna())
    ha_event = pd.Series(np.select([to_green, to_red], ["red_to_green", "green_to_red"],
                                   default="none"), index=members).where(current.notna() & prior.notna())
    fast, slow = ema(close, q.ema_fast), ema(close, q.ema_slow)
    macd = ema(close, q.macd_fast) - ema(close, q.macd_slow)
    line = ema(macd, q.macd_signal)
    ema_event, ema_match = signal(fast - slow, q.ema_sessions_ago, q.ema_rule)
    macd_event, macd_match = signal(macd - line, q.macd_sessions_ago, q.macd_rule)
    selected = ema_match & macd_match
    if q.heikin_ashi_rule != "any":
        selected &= to_green if q.heikin_ashi_rule == "red_to_green" else to_red
    for distance, limit in ((below, q.below_high_pct), (below_low, q.below_low_pct),
                            (above_high, q.above_high_pct), (above, q.above_low_pct)):
        if limit is not None:
            selected &= distance.between(-1e-8, limit + 1e-8)
    if q.range_levels:
        level_matches = []
        for level in q.range_levels:
            distance = below if level.metric == "below_high_pct" else above
            level_matches.append(distance.ge(level.value - 1e-8) if level.operator == "at_least"
                                 else distance.le(level.value + 1e-8))
        combined = level_matches[0]
        for match in level_matches[1:]:
            combined = combined & match if q.range_mode == "all" else combined | match
        selected &= combined
    # Express adjusted indicators in latest traded-price units.
    raw = h.raw.loc[asof, members]
    scale = raw / last
    frame = (
        pd.DataFrame(
            {
                "close": raw,
                "high_52w": high * scale,
                "low_52w": low * scale,
                "below_high_pct": below,
                "above_low_pct": above,
                "above_high_pct": above_high,
                "below_low_pct": below_low,
                "heikin_ashi_open": ha_open.iloc[-1] * scale,
                "heikin_ashi_close": ha_close.iloc[-1] * scale,
                "heikin_ashi_color": ha_color,
                "heikin_ashi_transition": ha_event,
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
    frame = frame.rename_axis("ticker").reset_index()
    cap_by_ticker = {ticker: cap for cap, code in CAP_INDEX.items()
                     for ticker in h.groups.get(code, set())}
    frame["cap"] = frame["ticker"].map(cap_by_ticker)
    frame["industry"] = frame["ticker"].map(h.industries)
    frame = frame.astype(object)
    result.update(
        priced=int(last.notna().sum()),
        range_coverage=int(covered.sum()),
        rows=frame.where(frame.notna(), None).to_dict("records"),
    )
    return result


class PriceUpdate(BaseModel):
    completed_at: datetime
    trade_date: date
    method: Literal["Scheduled capture", "Manual capture", "End-of-day update"]


class MarketStatus(BaseModel):
    connected: bool | None
    expires_at: datetime | None
    last_update: PriceUpdate | None
    scheduled_date: date
    scheduled_status: Literal["complete", "partial", "failed", "upcoming", "awaiting_result", "unrecorded", "market_closed"]
    scheduled_ended_at: datetime | None


@router.get("/screener/market-status", response_model=MarketStatus)
def screen_market_status(_user: CurrentUser):
    now = datetime.now(TZ)
    today = now.date()
    try:
        session = connection_status()
    except RedisError:
        session = {"connected": None, "expires_at": None}

    with connect(read_only=True) as db:
        latest = db.execute("""
            SELECT run_id, job, ended_at FROM run_log
            WHERE job IN ('angel_market', 'angel_eod') AND status='ok'
              AND ended_at IS NOT NULL AND rows_written > 0
            ORDER BY ended_at DESC LIMIT 1
        """).first()
        scheduled = db.execute("""
            SELECT status, ended_at FROM run_log WHERE run_id=? AND job='angel_market'
        """, [f"angel-market-{today}"]).first()
    update = None
    if latest:
        method = ("End-of-day update" if latest.job == "angel_eod" else
                  "Scheduled capture" if latest.run_id.startswith("angel-market-") else "Manual capture")
        update = PriceUpdate(completed_at=latest.ended_at.replace(tzinfo=UTC),
                             trade_date=date.fromisoformat(latest.run_id[-10:]), method=method)
    capture_at = datetime.combine(today, time(15, 16), TZ)
    if scheduled and scheduled.status in {"ok", "partial", "failed"}:
        status = "complete" if scheduled.status == "ok" else scheduled.status
    else:
        calendar = market_calendar().schedule(today, today)
        if calendar.empty or not calendar.iloc[0].market_open <= capture_at < calendar.iloc[0].market_close:
            status = "market_closed"
        elif now < capture_at:
            status = "upcoming"
        elif now.time() < time(15, 30):
            status = "awaiting_result"
        else:
            status = "unrecorded"
    return MarketStatus(connected=session["connected"], expires_at=session["expires_at"], last_update=update,
                        scheduled_date=today, scheduled_status=status,
                        scheduled_ended_at=scheduled.ended_at.replace(tzinfo=UTC) if scheduled and scheduled.ended_at else None)


@router.post("/screener/run", response_model=ScreenResult)
def run_screen(query: Screen, _user: CurrentUser):
    return evaluate(cached_history(), query)


@router.post("/screener/stock/{ticker}", response_model=StockIndicators)
def stock_indicators(ticker: str, periods: Screen, _user: CurrentUser):
    history = cached_history()
    ticker = ticker.upper()
    if ticker not in history.raw.columns:
        raise HTTPException(404, "No active listing for this ticker.")
    single = replace(history, members=pd.Index([ticker], name="ticker"))
    filters = periods if isinstance(periods, Screen) else Screen(**periods.model_dump())
    unfiltered = filters.model_copy(update={"index_code": "NIFTY500", "industry": None, "cap": None,
                                            "fo_only": False, "below_high_pct": None, "above_low_pct": None,
                                            "above_high_pct": None, "below_low_pct": None,
                                            "heikin_ashi_rule": "any",
                                            "range_levels": [],
                                            "ema_rule": "any", "macd_rule": "any"})
    result = evaluate(single, unfiltered)
    filtered = evaluate(single, filters)
    return {"asof": result["asof"], "ema_date": result["ema_date"], "macd_date": result["macd_date"],
            "price_source": result["price_source"], "exchange_trade_at": result["exchange_trade_at"],
            "values": next(iter(result["rows"]), None),
            "matches_filters": bool(filtered["rows"]) and (not filters.screen_universe or ticker in history.members)}
