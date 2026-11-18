"""Pydantic request / response models for the FastAPI layer.

Keeping these in one file so the frontend TypeScript types stay easy to
generate (openapi.json -> openapi-typescript -> api.ts).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


# ------------------------------------------------------------------ core
class HealthOut(BaseModel):
    status: Literal["ok", "degraded"]
    tickers: int | None = None
    tickers_with_prices: int | None = None
    price_rows: int | None = None
    error: str | None = None


# -------------------------------------------------------------- universe
class UniverseRow(BaseModel):
    ticker: str
    symbol: str | None = None
    sector: str | None = None
    industry: str | None = None


# ----------------------------------------------------------------- prices
class PriceBar(BaseModel):
    date: date
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    adj_close: float | None = None
    volume: int | None = None


# ------------------------------------------------------------------- news
class NewsItem(BaseModel):
    published_at: datetime
    headline: str | None = None
    source: str | None = None
    url: str | None = None
    polarity: float | None = None
    pos: float | None = None
    neg: float | None = None
    neu: float | None = None


class SentimentDay(BaseModel):
    date: date
    polarity: float | None = None
    n_headlines: int | None = None


# ----------------------------------------------------------------- agents
AgentName = Literal["technical", "sentiment", "momentum", "fundamental"]


class AgentScoreRow(BaseModel):
    ticker: str
    score: float
    imputed: bool = False
    sector: str | None = None
    industry: str | None = None


# ---------------------------------------------------------------- combine
class CombineRequest(BaseModel):
    asof: date | None = None
    n: int = Field(10, ge=1, le=50, description="Names per side")
    mode: Literal["weighted", "consensus", "hybrid"] = "weighted"
    weights: dict[str, float] | None = None
    max_names_per_sector: int = 3
    consensus_k: int = 3


class CombineRow(BaseModel):
    ticker: str
    sector: str | None = None
    composite: float
    technical: float = 50.0
    sentiment: float = 50.0
    momentum: float = 50.0
    fundamental: float = 50.0


class CombineOut(BaseModel):
    asof: date
    mode: str
    weights: dict[str, float]
    longs: list[CombineRow]
    shorts: list[CombineRow]


# ---------------------------------------------------------------- backtest
class BacktestRequest(BaseModel):
    start: date
    end: date
    n: int = Field(10, ge=3, le=30)


class EquityPoint(BaseModel):
    date: date
    equity: float


class BacktestSummary(BaseModel):
    start: date
    end: date
    n_per_side: int
    rebalance: str = "monthly"
    total_return: float
    annual_return: float
    annual_vol: float
    sharpe: float
    max_drawdown: float
    n_days: int
    longs_last: list[str] = []
    shorts_last: list[str] = []
    equity_curve: list[EquityPoint] = []


class BacktestJobRef(BaseModel):
    job_id: str
    status: Literal["queued", "started", "finished", "failed"]
    result_key: str | None = None


# -------------------------------------------------------------------- auth
class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = 3600


class UserOut(BaseModel):
    id: str
    email: str
    is_admin: bool = False
