"""Company profiles assembled from dated, redistributable local observations."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from stock_agents.api.auth import CurrentUser
from stock_agents.ingest.provider_values import number
from stock_agents.ingest.screen_indices import CAP_INDEX, INDEX_FILES
from stock_agents.storage.warehouse import connect

router = APIRouter(tags=["stocks"])
Unit = Literal["INR", "INR/share", "fraction", "multiple", "count", "rating"]
METRICS = {
    "market_cap": ("Market capitalization", "INR"),
    "eps_ttm": ("Diluted EPS · TTM", "INR/share"),
    "pe_ttm": ("Trailing P/E", "multiple"),
    "forward_pe": ("Forward P/E", "multiple"),
    "price_to_book": ("Price / book", "multiple"),
    "price_to_sales": ("Price / sales", "multiple"),
    "ev_ebitda": ("EV / EBITDA", "multiple"),
    "dividend_yield": ("Dividend yield", "fraction"),
    "roe_ttm": ("Return on equity · TTM", "fraction"),
    "roa_ttm": ("Return on assets · TTM", "fraction"),
    "net_margin_ttm": ("Net margin · TTM", "fraction"),
    "operating_margin_ttm": ("Operating margin · TTM", "fraction"),
    "revenue_growth_yoy": ("Quarterly revenue growth · YoY", "fraction"),
    "eps_growth_yoy": ("Quarterly earnings growth · YoY", "fraction"),
    "eps_fy1": ("Consensus EPS · FY1", "INR/share"),
    "eps_fy2": ("Consensus EPS · FY2", "INR/share"),
    "revisions_up_30d": ("Upward EPS revisions · 30d", "count"),
    "revisions_down_30d": ("Downward EPS revisions · 30d", "count"),
}
INDEX_LABELS = {
    "NIFTY500": "Nifty 500",
    "NSE_FO": "NSE F&O",
    **{k: v[0] for k, v in INDEX_FILES.items()},
}


class Metric(BaseModel):
    key: str
    label: str
    value: float
    unit: Unit
    source: str
    asof: date
    known_on: date


class Quote(BaseModel):
    date: date
    known_on: date
    source: str
    open: float | None
    high: float | None
    low: float | None
    close: float
    adjusted_close: float | None
    volume: int
    previous_date: date | None
    previous_close: float | None
    change: float | None
    change_pct: float | None


class Membership(BaseModel):
    code: str
    name: str
    observed_on: date


class Earnings(BaseModel):
    fiscal_period: str
    reported: float | None
    estimate: float | None
    surprise_pct: float | None
    report_date: date
    known_on: date
    source: str


class Action(BaseModel):
    kind: str
    ex_date: date
    value: float | None
    unit: str
    source: str
    known_on: date


class Profile(BaseModel):
    ticker: str
    company_name: str | None
    isin: str | None
    venue: str | None
    series: str | None
    active: bool
    identity_source: str | None
    identity_date: date | None
    sector: str | None
    industry: str | None
    classification_source: str | None
    classification_date: date | None
    cap_segment: str | None
    memberships: list[Membership]
    quote: Quote | None
    fundamentals: list[Metric]
    analyst: list[Metric]
    earnings: list[Earnings]
    actions: list[Action]


def load_profile(db, ticker: str, today: date) -> Profile:
    identity = (
        db.execute(
            """
        SELECT s.active,s.isin,s.eodhd_symbol,c.company_name,c.venue,c.series,c.source,c.observed_on
        FROM symbology s LEFT JOIN company_reference c ON c.ticker=s.ticker
          AND c.isin IS NOT DISTINCT FROM s.isin AND c.observed_on<=?
          AND c.source IN ('nse_indices','nse_fo','seed_csv')
        WHERE s.ticker=?""",
            [today, ticker],
        )
        .mappings()
        .first()
    )
    if identity is None:
        raise HTTPException(404, "Ticker is absent from the local securities directory")
    params = [ticker, today, today]
    cls = (
        db.execute(
            """SELECT sector,industry,source,known_date FROM classification
        WHERE ticker=? AND effective_date<=? AND known_date<=?
          AND source IN ('nse_indices','seed_csv','eodhd','industry_sector_map')
        ORDER BY effective_date DESC,known_date DESC,
          (NULLIF(TRIM(sector),'') IS NOT NULL) DESC,(source='nse_indices') DESC,source LIMIT 1""",
            params,
        )
        .mappings()
        .first()
        or {}
    )
    memberships = [
        Membership(code=code, name=INDEX_LABELS.get(code, code), observed_on=known)
        for code, known in db.execute(
            """SELECT index_code,MAX(known_on) FROM index_membership
            WHERE ticker=? AND joined_on<=? AND known_on<=? AND (left_on IS NULL OR left_on>?)
            GROUP BY index_code ORDER BY index_code""",
            [*params, today],
        )
    ]
    segments = [seg for seg, code in CAP_INDEX.items() if any(m.code == code for m in memberships)]
    # Restrict the common path to recent Timescale chunks. An older suspended
    # listing or one recent trade still gets its exact previous observation.
    quote_sql = """SELECT DISTINCT ON (date) date,open,high,low,close,adj_close,volume,source,known_date
        FROM prices_daily WHERE ticker=? AND date<=? AND known_date<=? AND volume>0
        AND close>0 AND close<'Infinity'::double precision AND source IN ('angel_one','eodhd','nse_bhavcopy')
        {window} ORDER BY date DESC,(source='angel_one') DESC,(source='eodhd') DESC,known_date DESC LIMIT 2"""
    cutoff = today - timedelta(days=14)
    prices = db.execute(quote_sql.format(window="AND date>=?"), [*params, cutoff]).mappings().all()
    if len(prices) < 2:
        older = (
            db.execute(quote_sql.format(window="AND date<?"), [*params, cutoff]).mappings().all()
        )
        prices.extend(older[: 2 - len(prices)])
    quote = None
    if prices:
        last = prices[0]
        prev = prices[1] if len(prices) > 1 else None
        change = last["close"] - prev["close"] if prev else None
        quote = Quote(
            date=last["date"],
            known_on=last["known_date"],
            source=last["source"],
            open=number(last["open"]),
            high=number(last["high"]),
            low=number(last["low"]),
            close=last["close"],
            adjusted_close=number(last["adj_close"]),
            volume=last["volume"],
            previous_date=prev["date"] if prev else None,
            previous_close=prev["close"] if prev else None,
            change=change,
            change_pct=100 * change / prev["close"] if prev else None,
        )

    def metrics(table):
        rows = db.execute(
            f"""SELECT DISTINCT ON (metric) metric,value,source,effective_date,known_date
            FROM {table} WHERE ticker=? AND effective_date<=? AND known_date<=? AND source='eodhd'
            ORDER BY metric,effective_date DESC,known_date DESC""",
            params,
        )
        found = {}
        for key, value, source, asof, known in rows:
            if key in METRICS and number(value) is not None:
                label, unit = METRICS[key]
                found[key] = Metric(
                    key=key,
                    label=label,
                    unit=unit,
                    value=value,
                    source=source,
                    asof=asof,
                    known_on=known,
                )
        return [found[key] for key in METRICS if key in found]

    fundamentals = metrics("fundamentals_pit")
    analyst = metrics("estimates_pit")
    ratings = (
        db.execute(
            """SELECT rating_mean,target_mean,n_analysts,source,effective_date,known_date
        FROM analyst_pit WHERE ticker=? AND effective_date<=? AND known_date<=? AND source='eodhd'
        ORDER BY effective_date DESC,known_date DESC LIMIT 1""",
            params,
        )
        .mappings()
        .first()
    )
    if ratings:
        for key, label, unit in [
            ("rating_mean", "Mean analyst rating", "rating"),
            ("target_mean", "Mean price target", "INR/share"),
            ("n_analysts", "Analysts", "count"),
        ]:
            if number(ratings[key]) is not None:
                analyst.append(
                    Metric(
                        key=key,
                        label=label,
                        unit=unit,
                        value=ratings[key],
                        source=ratings["source"],
                        asof=ratings["effective_date"],
                        known_on=ratings["known_date"],
                    )
                )
    earnings = [
        Earnings(
            fiscal_period=p,
            reported=number(actual),
            estimate=number(est),
            surprise_pct=number(surprise),
            report_date=day,
            known_on=known,
            source=source,
        )
        for p, actual, est, surprise, day, known, source in db.execute(
            """
            SELECT fiscal_period,eps_reported,eps_estimate,surprise_pct,report_date,known_date,source
            FROM earnings_surprise WHERE ticker=? AND report_date<=? AND known_date<=? AND source='eodhd'
            ORDER BY report_date DESC,fiscal_period DESC LIMIT 4""",
            params,
        )
    ]
    units = {
        "split": "new shares per old share",
        "bonus": "additional shares per held share",
        "dividend": "INR/share",
        "distribution": "INR/unit",
    }
    actions = [
        Action(
            kind=kind,
            ex_date=day,
            value=number(value),
            unit=units.get(kind, ""),
            source=source,
            known_on=known,
        )
        for kind, day, value, source, known in db.execute(
            """SELECT DISTINCT ON (ex_date,action_type)
            action_type,ex_date,value,source,known_date FROM corporate_actions
            WHERE ticker=? AND ex_date<=? AND known_date<=? AND source IN ('eodhd','nse')
            ORDER BY ex_date DESC,action_type,(source='nse') DESC,known_date DESC LIMIT 5""",
            params,
        )
    ]
    symbol = identity["eodhd_symbol"] or ""
    return Profile(
        ticker=ticker,
        company_name=identity["company_name"],
        isin=identity["isin"],
        active=identity["active"],
        venue=identity["venue"] or ("NSE" if symbol.endswith(".NSE") else None),
        series=identity["series"],
        identity_source=identity["source"],
        identity_date=identity["observed_on"],
        sector=cls.get("sector"),
        industry=cls.get("industry"),
        classification_source=cls.get("source"),
        classification_date=cls.get("known_date"),
        cap_segment=segments[0] if len(segments) == 1 else None,
        memberships=memberships,
        quote=quote,
        fundamentals=fundamentals,
        analyst=analyst,
        earnings=earnings,
        actions=actions,
    )


@router.get("/stock-profile/{ticker}", response_model=Profile)
def stock_profile(ticker: str, _user: CurrentUser) -> Profile:
    with connect(read_only=True) as db:
        return load_profile(
            db, ticker.strip().upper(), datetime.now(ZoneInfo("Asia/Kolkata")).date()
        )
