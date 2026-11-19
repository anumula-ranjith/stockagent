"""Normalize vendor snapshots without treating unreported observations as zero."""

from __future__ import annotations

import math
from datetime import date


def number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def ratio(numerator, denominator):
    n, d = number(numerator), number(denominator)
    return n / d if n is not None and d is not None and d > 0 else None


HIGHLIGHTS = {
    "roe_ttm": "ReturnOnEquityTTM",
    "roa_ttm": "ReturnOnAssetsTTM",
    "net_margin_ttm": "ProfitMargin",
    "operating_margin_ttm": "OperatingMarginTTM",
    "revenue_growth_yoy": "QuarterlyRevenueGrowthYOY",
    "eps_growth_yoy": "QuarterlyEarningsGrowthYOY",
    "pe_ttm": "PERatio",
    "market_cap": "MarketCapitalization",
    "eps_ttm": "DilutedEpsTTM",
    "peg": "PEGRatio",
    "dividend_yield": "DividendYield",
}
VALUATION = {
    "forward_pe": "ForwardPE",
    "ev_ebitda": "EnterpriseValueEbitda",
    "price_to_sales": "PriceSalesTTM",
    "price_to_book": "PriceBookMRQ",
}
ESTIMATES = {"eps_fy1", "eps_fy2", "revisions_up_30d", "revisions_down_30d", "rating_change_1m"}


def _section(data, key):
    # EODHD encodes unavailable sections as the literal string "NA".
    section = data.get(key)
    return section if isinstance(section, dict) else {}


def snapshot_rows(ticker: str, values: dict, observed: date, source: str,
                  analyst_counts: dict[str, int] | None = None) -> dict[str, list]:
    rows: dict[str, list] = {
        "fundamentals_pit": [],
        "estimates_pit": [],
        "analyst_pit": [],
        "earnings_surprise": [],
    }
    base = dict(ticker=ticker, source=source, effective_date=observed, known_date=observed)
    analyst = {}
    for metric, raw in values.items():
        value = number(raw)
        if value is None:
            continue
        if metric in {"rating_mean", "target_mean"}:
            analyst[metric] = value
        elif metric == "recommendation_count":
            if value.is_integer() and 0 <= value <= 2_147_483_647:
                analyst["n_analysts"] = int(value)
        elif metric in ESTIMATES:
            rows["estimates_pit"].append(dict(**base, metric=metric, value=value,
                                              n_analysts=(analyst_counts or {}).get(metric)))
        else:
            # These are observed vendor snapshots, even when a constituent
            # figure is described as LTM. Never backdate to a fiscal period end.
            rows["fundamentals_pit"].append(
                dict(**base, metric=metric, value=value, fiscal_period=f"snapshot:{observed}")
            )
    if analyst:
        rows["analyst_pit"].append(
            dict(
                **base,
                rating_mean=analyst.get("rating_mean"),
                target_mean=analyst.get("target_mean"),
                n_analysts=analyst.get("n_analysts"),
            )
        )
    return rows


def eodhd_rows(
    ticker: str, isin: str, data: dict, observed: date, regional_ids=None
) -> dict[str, list]:
    if not data or not isinstance(data.get("General"), dict):
        return snapshot_rows(ticker, {}, observed, "eodhd")
    general = data["General"]
    alias = general.get("ISIN")
    same_security = (regional_ids or {}).get(isin)
    if (
        general.get("Code") != ticker
        or general.get("Exchange") != "NSE"
        or (
            alias
            and isin
            and alias != isin
            and not (same_security and same_security == (regional_ids or {}).get(alias))
        )
    ):
        raise ValueError("EODHD security identity mismatch")
    h = _section(data, "Highlights")
    valuation = _section(data, "Valuation")
    values = {name: h.get(key) for name, key in HIGHLIGHTS.items()}
    values.update({name: valuation.get(key) for name, key in VALUATION.items()})
    values["gross_margin"] = ratio(h.get("GrossProfitTTM"), h.get("RevenueTTM"))
    analyst_counts = {}
    for item in _section(data, "Earnings::Trend").values():
        if item.get("period") == "0y":
            values.update(
                eps_fy1=item.get("earningsEstimateAvg"),
                revisions_up_30d=item.get("epsRevisionsUpLast30days"),
                revisions_down_30d=item.get("epsRevisionsDownLast30days"),
            )
            count = number(item.get("earningsEstimateNumberOfAnalysts"))
            if count is not None and count >= 0 and count.is_integer():
                analyst_counts["eps_fy1"] = int(count)
        elif item.get("period") == "+1y":
            values["eps_fy2"] = item.get("earningsEstimateAvg")
            count = number(item.get("earningsEstimateNumberOfAnalysts"))
            if count is not None and count >= 0 and count.is_integer():
                analyst_counts["eps_fy2"] = int(count)
    rows = snapshot_rows(ticker, values, observed, "eodhd", analyst_counts)
    for item in _section(data, "Earnings::History").values():
        if not item.get("reportDate") or not item.get("date"):
            continue
        report = date.fromisoformat(item["reportDate"])
        period = date.fromisoformat(item["date"])
        surprise = number(item.get("surprisePercent"))
        if period <= report <= observed and surprise is not None:
            rows["earnings_surprise"].append(
                dict(
                    ticker=ticker,
                    fiscal_period=str(period),
                    eps_reported=number(item.get("epsActual")),
                    eps_estimate=number(item.get("epsEstimate")),
                    surprise_pct=surprise,
                    report_date=report,
                    known_date=observed,
                    source="eodhd",
                )
            )
    return rows
