"""Configurable agent and portfolio selection shared by the dashboard and historical replay."""

from dataclasses import dataclass, field
from datetime import date
from typing import Annotated, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

Weight = Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]
TECH = {
    "rsi14": 5,
    "macd_hist": 5,
    "vs_sma50": 5,
    "vs_sma200": 5,
    "golden_cross": 3,
    "adx14_signed": 5,
    "bb_pctb": 3,
    "stoch_k": 3,
    "vol_surge": 5,
    "obv_trend": 5,
    "atr_pct": 3,
    "prox_52w_high": 5,
}
SENT = {
    "news_tone_7d": 8,
    "news_volume": 3,
    "hot_sector": 6,
    "est_revisions": 6,
    "rating_change_1m": 4,
    "social_buzz": 0,
    "insider_activity": 3,
    "short_interest": 3,
}
MOM = {"ret_1m": 3, "ret_3m": 6, "ret_6m": 7, "ret_12_1": 9, "rel_str": 3, "accel": 2}
PILLARS = {
    "value": [
        "pe_ttm",
        "forward_pe",
        "price_to_book",
        "ev_ebitda",
        "price_to_sales",
        "fcf_yield",
        "peg",
    ],
    "quality": [
        "roe_ttm",
        "roa_ttm",
        "roic",
        "gross_margin",
        "operating_margin_ttm",
        "net_margin_ttm",
    ],
    "growth": ["revenue_growth_yoy", "eps_growth_yoy", "eps_surprise", "forward_eps_growth"],
    "health": ["debt_equity", "current_ratio", "interest_coverage"],
    "shareholder_yield": ["dividend_yield", "buyback_yield"],
}
PILLAR_WEIGHTS = {"value": 25, "quality": 25, "growth": 25, "health": 15, "shareholder_yield": 10}
AGENTS = ["technical", "sentiment", "momentum", "fundamental"]
LOWER = {
    "atr_pct",
    "pe_ttm",
    "forward_pe",
    "price_to_book",
    "ev_ebitda",
    "price_to_sales",
    "peg",
    "debt_equity",
}
PEAK = {"rsi14": 60, "bb_pctb": 0.75, "stoch_k": 65}
FUND = {key: 1 for keys in PILLARS.values() for key in keys}
DEFAULT_FACTORS = {**TECH, **SENT, **MOM, **FUND}
Agent = Literal["technical", "sentiment", "momentum", "fundamental"]


class RankSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    factors: dict[str, Weight] = Field(default_factory=lambda: DEFAULT_FACTORS.copy())
    pillars: dict[str, Weight] = Field(default_factory=lambda: PILLAR_WEIGHTS.copy())
    agents: dict[Agent, Weight] = Field(default_factory=lambda: dict.fromkeys(AGENTS, 25))
    rsi_min: float = Field(30, ge=0, le=100)
    rsi_max: float = Field(80, ge=0, le=100)
    min_traded_value: float = Field(0, ge=0, le=1e13)
    tech_above_ma: bool = False
    mom_above_ma: bool = False
    vol_adjust: bool = False
    min_headlines: int = Field(3, ge=0, le=10000)
    boost_sectors: bool = True
    short_squeeze: bool = False
    sector_neutral: bool = True
    max_pe: float = Field(0, ge=0, le=10000)
    max_de: float = Field(0, ge=0, le=10000)
    positive_fcf: bool = False
    size: int = Field(10, ge=1, le=50)
    max_sector: int = Field(3, ge=0, le=50)
    agree: int = Field(3, ge=1, le=4)
    mode: Literal["weighted", "consensus", "hybrid"] = "weighted"

    @model_validator(mode="after")
    def validate_keys(self):
        if self.factors.keys() - DEFAULT_FACTORS.keys() or self.pillars.keys() - PILLARS.keys():
            raise ValueError("Unknown factor or pillar")
        if self.rsi_min > self.rsi_max:
            raise ValueError("RSI minimum exceeds maximum")
        return self


def feature(frame, key):
    return pd.to_numeric(
        frame.get(key, pd.Series(index=frame.index, dtype=float)), errors="coerce"
    ).replace([np.inf, -np.inf], np.nan)


def rank(values, sectors=None, comparison_subject=None):
    if comparison_subject is not None:
        # Preserve the benchmark's scores. Only the subject gets an insertion
        # percentile, including itself in its tie group and denominator.
        reference = values.drop(comparison_subject)
        reference_sectors = None if sectors is None else sectors.loc[reference.index]
        ranked = rank(reference, reference_sectors).reindex(values.index)
        if sectors is not None:
            reference = reference.loc[reference_sectors == sectors.at[comparison_subject]]
        peers = reference.dropna()
        subject = values.at[comparison_subject]
        if len(peers) and pd.notna(subject):
            ranked.at[comparison_subject] = (
                100
                * ((peers < subject).sum() + 0.5 * ((peers == subject).sum() + 1))
                / (len(peers) + 1)
            )
        return ranked
    grouped = values if sectors is None else values.groupby(sectors)
    counts = values.count() if sectors is None else grouped.transform("count")
    return (100 * (grouped.rank() - 0.5) / counts).where(values.notna())


def observed_weights(frame, weights):
    """Configured positive weights with observations in the cross-section."""
    return {k: v for k, v in weights.items() if v > 0 and k in frame and frame[k].notna().any()}


def blend(frame, weights):
    """Neutral 50 for individual gaps. A wholly missing signal stays unavailable."""
    valid = observed_weights(frame, weights)
    if not valid:
        return pd.Series(np.nan, index=frame.index)
    factors = frame[list(valid)]
    return (factors.fillna(50).mul(pd.Series(valid)).sum(axis=1) / sum(valid.values())).where(
        factors.notna().any(axis=1)
    )


@dataclass
class ScoreEvidence:
    """Optional intermediates from the same pass that selects the candidate books."""

    factor_ranks: dict[str, pd.DataFrame] = field(default_factory=dict)
    pillars: pd.DataFrame = field(default_factory=pd.DataFrame)
    long_filters: pd.DataFrame = field(default_factory=pd.DataFrame)
    sentiment_bonus: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))


def score_book(raw, cfg: RankSettings, *, evidence: ScoreEvidence | None = None):
    frame = raw.copy()
    sector = frame.get("sector", pd.Series(index=frame.index, dtype=str)).fillna("Unclassified")
    scores = pd.DataFrame(index=frame.index)
    passes = {}
    for agent, keys in [
        ("technical", TECH),
        ("sentiment", SENT),
        ("momentum", MOM),
        ("fundamental", FUND),
    ]:
        ranks = {}
        for key in keys:
            value = feature(frame, key)
            if key in LOWER or (key == "short_interest" and not cfg.short_squeeze):
                if key in {"pe_ttm", "forward_pe", "peg", "ev_ebitda"}:
                    value = value.where(value > 0)
                value = -value
            elif key in PEAK:
                value = -(value - PEAK[key]).abs()
            if agent == "momentum" and cfg.vol_adjust:
                value = value / feature(frame, "volatility").where(lambda s: s > 0)
            ranks[key] = rank(
                value,
                sector if agent == "fundamental" and cfg.sector_neutral else None,
                raw.attrs.get("comparison_subject"),
            )
        ranked = pd.DataFrame(ranks, index=frame.index)
        if evidence is not None:
            evidence.factor_ranks[agent] = ranked
        if agent == "fundamental":
            pillars = {
                p: blend(ranked, {k: cfg.factors.get(k, 0) for k in items})
                for p, items in PILLARS.items()
            }
            pillar_frame = pd.DataFrame(pillars, index=frame.index)
            scores[agent] = blend(pillar_frame, cfg.pillars)
            if evidence is not None:
                evidence.pillars = pillar_frame
        else:
            scores[agent] = blend(ranked, {k: cfg.factors.get(k, 0) for k in keys})
    hot = feature(frame, "hot_sector").groupby(sector).first().dropna().nlargest(3).index
    if cfg.boost_sectors:
        original = scores["sentiment"].copy() if evidence is not None else None
        scores["sentiment"] = (scores.sentiment + 10 * sector.isin(hot)).clip(upper=100)
        if evidence is not None:
            evidence.sentiment_bonus = scores["sentiment"] - original
    passes["technical"] = pd.Series(True, index=frame.index)
    if cfg.rsi_min > 0 or cfg.rsi_max < 100:
        passes["technical"] &= feature(frame, "rsi14").between(cfg.rsi_min, cfg.rsi_max)
    if cfg.min_traded_value:
        passes["technical"] &= feature(frame, "traded_value") >= cfg.min_traded_value
    if cfg.tech_above_ma:
        passes["technical"] &= feature(frame, "vs_sma200") > 0
    passes["momentum"] = (
        feature(frame, "vs_sma200") > 0 if cfg.mom_above_ma else pd.Series(True, index=frame.index)
    )
    passes["sentiment"] = feature(frame, "headlines").fillna(0) >= cfg.min_headlines
    passes["fundamental"] = pd.Series(True, index=frame.index)
    if cfg.max_pe:
        passes["fundamental"] &= feature(frame, "pe_ttm").between(0, cfg.max_pe, inclusive="right")
    if cfg.max_de:
        passes["fundamental"] &= feature(frame, "debt_equity") <= cfg.max_de
    if cfg.positive_fcf:
        passes["fundamental"] &= feature(frame, "fcf_yield") > 0
    scores["composite"] = blend(scores, cfg.agents)
    frame["sector"] = sector
    for key in scores:
        frame[key] = scores[key]

    books = {}
    book_member = frame.index != raw.attrs.get("comparison_subject")

    def select(key, mask_long, mask_short, cap=0):
        def pick(ascending, mask, exclude, limit):
            counts = {}
            names = []
            for ticker, _val in (
                frame.loc[mask, key]
                .dropna()
                .sort_index()
                .sort_values(ascending=ascending, kind="stable")
                .items()
            ):
                group = sector.loc[ticker]
                if ticker in exclude or cap and counts.get(group, 0) >= cap:
                    continue
                names.append(ticker)
                counts[group] = counts.get(group, 0) + 1
                if len(names) >= limit:
                    break
            return names

        # Reserve room for both sides in small universes. Long-list filters
        # apply before taking the highest-scoring eligible names.
        long_limit = min(cfg.size, (int(frame.loc[book_member, key].count()) + 1) // 2)
        longs = pick(False, mask_long & book_member, set(), long_limit)
        shorts = pick(True, mask_short & book_member, set(longs), cfg.size)
        return {"longs": longs, "shorts": shorts}

    allowed = pd.Series(True, index=frame.index)
    for agent in AGENTS:
        books[agent] = select(agent, passes[agent], allowed)
    active = [a for a in AGENTS if cfg.agents.get(a, 0) > 0 and scores[a].notna().any()]
    eligible = pd.DataFrame(passes, index=frame.index)
    if evidence is not None:
        evidence.long_filters = eligible
    # A name with an observed failing agent cannot enter the combined long book
    # on that agent's vote. Other eligible agents may still support it.
    supported = scores[active].where(eligible[active])
    long_ok = supported.notna().any(axis=1)
    short_ok = scores[active].notna().any(axis=1)
    if cfg.mode == "consensus":
        long_ok &= (supported.loc[book_member].rank(ascending=False, method="min") <= 20).sum(
            axis=1
        ) >= cfg.agree
        short_ok &= (scores.loc[book_member, active].rank(method="min") <= 20).sum(
            axis=1
        ) >= cfg.agree
    elif cfg.mode == "hybrid":
        long_ok &= ((scores[active] >= 40) & eligible[active]).all(axis=1)
        short_ok &= (scores[active] <= 60).all(axis=1)
    books["combined"] = select("composite", long_ok, short_ok, cfg.max_sector)
    return frame, books


def to_payload(raw, cfg, asof: date, price_date):
    frame, books = score_book(raw, cfg)
    available = {key: int(feature(raw, key).count()) for key in DEFAULT_FACTORS}
    rows = {}
    visible = set(DEFAULT_FACTORS) | set(AGENTS) | {"headlines", "composite", "volatility"}
    protected = raw.attrs.get("protected", {})
    for ticker in {t for book in books.values() for bookside in book.values() for t in bookside}:
        row = frame.loc[ticker]
        rows[ticker] = {
            "ticker": ticker,
            "sector": row["sector"],
            "values": {
                k: round(float(row[k]), 6)
                for k in visible & set(row.index)
                if pd.notna(row[k])
                and np.isfinite(row[k])
                and ticker not in protected.get(k, set())
            },
        }
    sectors = (
        feature(frame, "ret_20d")
        .groupby(frame.sector)
        .mean()
        .drop(index="Unclassified", errors="ignore")
        .dropna()
        .sort_values(ascending=False)
    )
    return {
        "asof": str(asof),
        "price_date": str(price_date) if price_date else None,
        "universe": len(frame),
        "coverage": available,
        "rows": rows,
        "books": books,
        "heat": [{"sector": k, "value": round(float(v), 6)} for k, v in sectors.items()],
    }
