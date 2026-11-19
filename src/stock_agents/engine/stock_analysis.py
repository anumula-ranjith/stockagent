"""Explain one constituent using the ranker's actual cross-sectional scoring pass."""

from datetime import date

import numpy as np
import pandas as pd

from stock_agents.engine.ranker import (
    AGENTS,
    LOWER,
    PEAK,
    PILLARS,
    RankSettings,
    ScoreEvidence,
    observed_weights,
    score_book,
)

# Units describe the stored input, before direction adjustment or peer ranking.
FACTOR_INFO = {
    "rsi14": (
        "Relative strength index",
        "index",
        "14-session average gains relative to total gains and losses.",
    ),
    "macd_hist": (
        "MACD histogram",
        "fraction",
        "12/26-session EMA spread minus its 9-session signal, divided by price.",
    ),
    "vs_sma50": (
        "Price vs 50-day average",
        "fraction",
        "Adjusted close relative to the 50-session moving average.",
    ),
    "vs_sma200": (
        "Price vs 200-day average",
        "fraction",
        "Adjusted close relative to the 200-session moving average.",
    ),
    "golden_cross": (
        "Moving-average spread",
        "fraction",
        "50-session moving average relative to the 200-session average.",
    ),
    "adx14_signed": (
        "Signed trend strength",
        "index",
        "14-session average directional strength with the sign of the latest directional move.",
    ),
    "bb_pctb": (
        "Bollinger band position",
        "fraction",
        "Position between the lower and upper 20-session, two-standard-deviation bands.",
    ),
    "stoch_k": (
        "Stochastic %K",
        "index",
        "Closing position within the 14-session high–low range, on a 0–100 scale.",
    ),
    "vol_surge": (
        "Volume surge",
        "multiple",
        "Latest traded volume relative to the previous 20-session average.",
    ),
    "obv_trend": (
        "Signed volume share",
        "fraction",
        "Net up-day minus down-day volume as a share of total volume over 20 sessions.",
    ),
    "atr_pct": (
        "Average true range",
        "fraction",
        "14-session mean true range divided by adjusted close.",
    ),
    "prox_52w_high": (
        "Distance from 52-week high",
        "fraction",
        "Adjusted close relative to the highest adjusted high in 252 sessions.",
    ),
    "news_tone_7d": (
        "Seven-day news tone",
        "polarity",
        "Average headline polarity weighted by headline count and a two-day half-life.",
    ),
    "news_volume": (
        "News volume vs normal",
        "multiple",
        "Average daily headlines in the last three days relative to the preceding 27 days.",
    ),
    "hot_sector": (
        "Sector return",
        "fraction",
        "Equal-weight mean of observed 20-session returns in the stock’s NSE sector.",
    ),
    "est_revisions": (
        "Net earnings revisions",
        "count",
        "Upward EPS estimate revisions minus downward revisions over 30 days.",
    ),
    "rating_change_1m": (
        "One-month rating change",
        "points",
        "Previous mean analyst rating minus current mean rating. Positive values indicate an improvement.",
    ),
    "social_buzz": ("Social mentions", "count", "Latest available daily mention count."),
    "insider_activity": (
        "Net insider purchases",
        "USD",
        "Reported purchases minus sales over 90 calendar days, measured in US dollars.",
    ),
    "short_interest": (
        "Short interest",
        "fraction",
        "Reported short interest as a share of float.",
    ),
    "ret_1m": ("One-month return", "fraction", "Adjusted close return over 21 market sessions."),
    "ret_3m": ("Three-month return", "fraction", "Adjusted close return over 63 market sessions."),
    "ret_6m": ("Six-month return", "fraction", "Adjusted close return over 126 market sessions."),
    "ret_12_1": (
        "12–1 month return",
        "fraction",
        "Adjusted return from 252 sessions ago to 21 sessions ago, skipping the latest month.",
    ),
    "rel_str": (
        "Relative three-month return",
        "fraction_points",
        "63-session return minus the universe mean return over the same period.",
    ),
    "accel": (
        "Return acceleration",
        "fraction_points",
        "Latest 21-session return minus the preceding 21-session return.",
    ),
    "pe_ttm": ("Trailing P/E", "multiple", "Market price per unit of trailing earnings."),
    "forward_pe": ("Forward P/E", "multiple", "Market price per unit of estimated earnings."),
    "price_to_book": (
        "Price to book",
        "multiple",
        "Market price relative to book value per share.",
    ),
    "ev_ebitda": (
        "EV / EBITDA",
        "multiple",
        "Enterprise value relative to earnings before interest, taxes, depreciation and amortization.",
    ),
    "price_to_sales": ("Price to sales", "multiple", "Equity market value relative to revenue."),
    "fcf_yield": (
        "Trailing free cash flow yield",
        "fraction",
        "Trailing free cash flow relative to equity market value.",
    ),
    "peg": ("PEG ratio", "multiple", "Price-to-earnings multiple relative to earnings growth."),
    "roe_ttm": (
        "Return on equity",
        "fraction",
        "Trailing earnings relative to shareholder equity.",
    ),
    "roa_ttm": ("Return on assets", "fraction", "Trailing earnings relative to assets."),
    "roic": (
        "Return on invested capital",
        "fraction",
        "Reported return on capital invested in operations.",
    ),
    "gross_margin": ("Gross margin", "fraction", "Gross profit as a share of revenue."),
    "operating_margin_ttm": (
        "Operating margin",
        "fraction",
        "Trailing operating profit as a share of revenue.",
    ),
    "net_margin_ttm": ("Net margin", "fraction", "Trailing net income as a share of revenue."),
    "revenue_growth_yoy": ("Revenue growth", "fraction", "Year-over-year change in revenue."),
    "eps_growth_yoy": ("EPS growth", "fraction", "Year-over-year change in earnings per share."),
    "eps_surprise": (
        "Earnings surprise",
        "fraction",
        "Reported earnings surprise relative to the consensus estimate.",
    ),
    "forward_eps_growth": (
        "Forward EPS growth",
        "fraction",
        "First-year forecast EPS relative to positive trailing EPS.",
    ),
    "debt_equity": ("Debt / equity", "multiple", "Reported debt relative to equity."),
    "current_ratio": (
        "Current ratio",
        "multiple",
        "Current assets relative to current liabilities.",
    ),
    "interest_coverage": (
        "Interest coverage",
        "multiple",
        "Earnings available to cover interest expense relative to that expense.",
    ),
    "dividend_yield": ("Dividend yield", "fraction", "Dividend income relative to market price."),
    "buyback_yield": (
        "Net buyback yield",
        "fraction",
        "Latest fiscal-year cash repurchases less issuance, relative to equity market value.",
    ),
}
SUBJECT = {
    "technical": "Chart conditions",
    "sentiment": "Sentiment signals",
    "momentum": "Price momentum",
    "fundamental": "Fundamental signals",
}


def _number(value):
    return float(value) if pd.notna(value) and np.isfinite(value) else None


def _fractions(frame, configured):
    weights = observed_weights(frame, configured)
    total = sum(weights.values())
    return {k: v / total for k, v in weights.items()}


def _position(values, ticker):
    score = _number(values.at[ticker])
    count = int(values.count())
    return {
        "score": score,
        "rank": None if score is None else 1 + int((values > score).sum()),
        "peers": count,
        "percentile": None
        if score is None
        else 100 * ((values < score).sum() + 0.5 * (values == score).sum()) / count,
    }


def _selection(book, ticker):
    for side, names in book.items():
        if ticker in names:
            return {
                "side": "long" if side == "longs" else "short",
                "place": names.index(ticker) + 1,
            }
    return {"side": None, "place": None}


def _direction(key, cfg):
    if key in PEAK:
        target = "75%" if key == "bb_pctb" else str(PEAK[key])
        return f"Closer to {target} ranks higher."
    if key in LOWER or (key == "short_interest" and not cfg.short_squeeze):
        return "Lower values rank higher."
    return "Higher values rank higher."


def _reading(agent, position, rows, bonus):
    score = position["score"]
    if score is None:
        return "No enabled factor has a scoreable observation for this stock."
    percentile = position["percentile"]
    if position["peers"] == 1:
        location = "have one scored stock for comparison"
    elif percentile >= 75:
        location = "rank in the upper quarter of scored stocks"
    elif percentile < 25:
        location = "rank in the lower quarter of scored stocks"
    else:
        location = "rank in the middle half of scored stocks"
    subject = "Momentum signals" if agent == "momentum" else SUBJECT[agent]
    message = f"{subject} {location}."
    observed = {
        r["key"]: r["value"]
        for r in rows
        if r["enabled"] and r["score"] is not None and r["value"] is not None
    }
    if agent == "technical" and "vs_sma50" in observed and "vs_sma200" in observed:
        short = "above" if observed["vs_sma50"] >= 0 else "below"
        long = "above" if observed["vs_sma200"] >= 0 else "below"
        message += f" The close is {abs(observed['vs_sma50']):.1%} {short} its 50-session average and {abs(observed['vs_sma200']):.1%} {long} its 200-session average."
    if agent == "momentum" and "ret_1m" in observed and "ret_6m" in observed:
        message += f" The stock returned {observed['ret_1m']:+.1%} over the latest month and {observed['ret_6m']:+.1%} over six months."
    if agent == "sentiment" and "news_tone_7d" in observed:
        tone = observed["news_tone_7d"]
        direction = "positive" if tone > 0 else "negative" if tone < 0 else "neutral"
        message += f" Recent headline tone is {direction} ({tone:+.2f} on a −1 to +1 scale)."
    if agent == "fundamental" and "roe_ttm" in observed and "revenue_growth_yoy" in observed:
        message += f" Trailing return on equity is {observed['roe_ttm']:.1%}, with year-over-year revenue growth of {observed['revenue_growth_yoy']:+.1%}."
    if (
        not any(row["contribution"] and abs(row["contribution"]) > 1e-9 for row in rows)
        and not bonus
    ):
        message += " The scored factors balance at the neutral level."
    if bonus:
        message += f" The sector boost adds {bonus:.1f} score points."
    return message


def stock_analysis(raw, cfg: RankSettings, asof: date, price_date, ticker: str):
    ticker = ticker.strip().upper()
    comparison = raw.attrs.get("comparison_subject")
    if comparison and comparison != ticker:
        raw = raw.drop(comparison)
        raw.attrs.pop("comparison_subject")
        comparison = None
    result = {
        "ticker": ticker,
        "asof": str(asof),
        "price_date": str(price_date) if price_date else None,
        "universe": len(raw) - int(bool(comparison)),
        "in_universe": ticker in raw.index and not comparison,
        "peer_comparison": bool(comparison),
    }
    if ticker not in raw.index:
        return result
    evidence = ScoreEvidence()
    frame, books = score_book(raw, cfg, evidence=evidence)
    sector = frame.at[ticker, "sector"]
    sector_mask = frame.sector.eq(sector)
    protected = raw.attrs.get("protected", {})
    mix = _fractions(frame[AGENTS], cfg.agents)
    composite = _position(frame.composite, ticker)
    composite.update(selection=_selection(books["combined"], ticker), mode=cfg.mode)
    agents = []
    for agent in AGENTS:
        ranks = evidence.factor_ranks[agent]
        position = _position(frame[agent], ticker)
        fund = agent == "fundamental"
        peers = ranks.loc[sector_mask] if fund and cfg.sector_neutral else ranks
        groups = PILLARS if fund else {agent: list(ranks)}
        peer_group = sector if fund and cfg.sector_neutral else "Nifty 500"
        if comparison:
            peer_group += " plus " + ticker
        pillar_mix = _fractions(evidence.pillars, cfg.pillars) if fund else {agent: 1.0}
        pillars, rows = [], []
        for group, keys in groups.items():
            group_weight = pillar_mix.get(group, 0)
            if fund:
                pillars.append(
                    {
                        "key": group,
                        "score": _number(evidence.pillars.at[ticker, group]),
                        "weight": cfg.pillars.get(group, 0),
                        "share": group_weight,
                    }
                )
            within = _fractions(ranks[keys], cfg.factors)
            for key in keys:
                label, unit, description = FACTOR_INFO[key]
                value = _number(raw.at[ticker, key]) if key in raw else None
                factor_score = _number(ranks.at[ticker, key])
                weight = cfg.factors.get(key, 0)
                effective = group_weight * within.get(key, 0)
                restricted = ticker in protected.get(key, set())
                if value is None:
                    status = "missing"
                elif (
                    factor_score is None
                    and comparison
                    and not peers.drop(index=ticker)[key].notna().any()
                ):
                    status = "no_comparable_peers"
                elif factor_score is None:
                    status = "unscoreable"
                else:
                    status = "observed"
                enabled = weight > 0 and (not fund or cfg.pillars.get(group, 0) > 0)
                contribution = (
                    (factor_score - 50) * effective
                    if factor_score is not None and effective
                    else None
                )
                rows.append(
                    {
                        "key": key,
                        "label": label,
                        "unit": unit,
                        "description": description,
                        "direction": _direction(key, cfg),
                        "pillar": group if fund else None,
                        "status": status,
                        "restricted": restricted,
                        "enabled": enabled,
                        "weight": weight,
                        "share": effective,
                        "value": None if restricted else value,
                        "score": factor_score,
                        "peer_observations": int(peers[key].count()),
                        "peer_universe": len(peers),
                        "contribution": contribution,
                    }
                )
        pushes = [r for r in rows if r["contribution"] is not None and r["contribution"] > 1e-9]
        pulls = [r for r in rows if r["contribution"] is not None and r["contribution"] < -1e-9]
        strongest = max(pushes, key=lambda r: r["contribution"])["key"] if pushes else None
        weakest = min(pulls, key=lambda r: r["contribution"])["key"] if pulls else None
        bonus = _number(evidence.sentiment_bonus.get(ticker)) if agent == "sentiment" else None
        share = mix.get(agent, 0)
        eligible = bool(evidence.long_filters.at[ticker, agent])
        observations = sum(r["enabled"] and r["score"] is not None for r in rows)
        agent_info = {
            "agent": agent,
            **position,
            "agent_weight": cfg.agents.get(agent, 0),
            "share": share,
            "composite_contribution": (position["score"] - 50) * share
            if position["score"] is not None
            else None,
            "selection": _selection(books[agent], ticker),
            "passes_long_filters": eligible,
            "observed": observations,
            "enabled": sum(r["enabled"] for r in rows),
            "strongest": strongest,
            "weakest": weakest,
            "bonus": bonus,
            "peer_group": peer_group,
            "vol_adjusted": agent == "momentum" and cfg.vol_adjust,
            "reading": _reading(agent, position, rows, bonus),
            "pillars": pillars,
            "factors": rows,
        }
        if agent == "sentiment":
            agent_info["headlines_7d"] = (
                _number(raw.at[ticker, "headlines"]) if "headlines" in raw else None
            )
            agent_info["min_headlines"] = cfg.min_headlines
        agents.append(agent_info)
    result.update(sector=sector, composite=composite, agents=agents)
    positive = [a for a in agents if (a["composite_contribution"] or 0) > 1e-9]
    negative = [a for a in agents if (a["composite_contribution"] or 0) < -1e-9]
    composite["observed"] = sum(a["score"] is not None and a["agent_weight"] > 0 for a in agents)
    if composite["score"] is None:
        reading = (
            "A composite requires an observed score from at least one agent with a positive weight."
        )
    else:
        reading = f"{composite['observed']} of {sum(a['agent_weight'] > 0 for a in agents)} enabled agents contribute observations."
        if positive:
            leader = max(positive, key=lambda a: a["composite_contribution"])
            reading += f" {leader['agent'].title()} adds the most support at {leader['composite_contribution']:+.1f} points relative to neutral (50)."
        if negative:
            laggard = min(negative, key=lambda a: a["composite_contribution"])
            reading += f" {laggard['agent'].title()} has the largest negative contribution at {laggard['composite_contribution']:.1f} points."
    composite["reading"] = reading
    return result
