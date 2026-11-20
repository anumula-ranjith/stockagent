"""Fetch EODHD statement ratios absent from the ranking snapshot."""
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from stock_agents.common.config import load_settings
from stock_agents.ingest.provider_values import number, ratio
from stock_agents.jobs.queue import sync_engine
from stock_agents.sources.eodhd import EODHDClient
from stock_agents.sources.factset import FactSetClient
from stock_agents.storage.postgres import Base


def latest(data, section, period):
    records = data.get("Financials", {}).get(section, {}).get(period, {})
    if not isinstance(records, dict):
        return {}
    today = date.today().isoformat()
    eligible = [r for r in records.values() if isinstance(r, dict)
                and isinstance(r.get("date"), str) and r["date"] <= today
                and (r.get("filing_date") or r.get("filingDate") or r["date"]) <= today]
    return max(eligible, key=lambda r: r.get("date", ""), default={})


def values(data):
    b = latest(data, "Balance_Sheet", "quarterly") or latest(data, "Balance_Sheet", "yearly")
    i = latest(data, "Income_Statement", "yearly")
    cf = latest(data, "Cash_Flow", "yearly")
    cap = number(data.get("Highlights", {}).get("MarketCapitalization"))
    equity = number(b.get("totalStockholderEquity"))
    debt = number(b.get("shortLongTermDebtTotal"))
    if debt is None:
        parts = [number(b.get(k)) for k in ("shortTermDebt", "longTermDebt")]
        debt = sum(parts) if all(v is not None for v in parts) else None
    out = {
        "debt_equity": ratio(debt, equity),
        "current_ratio": ratio(b.get("totalCurrentAssets"), b.get("totalCurrentLiabilities")),
        "interest_coverage": ratio(i.get("ebit") or i.get("operatingIncome"),
                                   abs(number(i.get("interestExpense")) or 0)),
        "fcf_yield": ratio(cf.get("freeCashFlow"), cap),
    }
    purchases = number(cf.get("salePurchaseOfStock"))
    if purchases is not None and cap and cap > 0:
        out["buyback_yield"] = -purchases / cap
    return {k: v for k, v in out.items() if v is not None}


def main():
    load_settings()
    client = EODHDClient.from_env()
    with sync_engine().connect() as conn:
        members = conn.execute(text("""SELECT s.ticker,s.eodhd_symbol,s.isin FROM symbology s
            WHERE s.active AND s.eodhd_symbol IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM fundamentals_pit f WHERE f.ticker=s.ticker
                  AND f.source='eodhd' AND f.effective_date=CURRENT_DATE
                  AND f.metric IN ('debt_equity','current_ratio','interest_coverage','fcf_yield','buyback_yield'))
            ORDER BY s.ticker""")).all()
    available = client.remaining_calls()
    reserve = max(100, int(load_settings().env("EODHD_NEWS_RESERVED_UNITS") or 12000))
    if available < len(members) * 10 + reserve:
        raise RuntimeError(f"EODHD quota insufficient: {available} units for {len(members)} symbols")
    observed = date.today()
    table = Base.metadata.tables["fundamentals_pit"]
    counts, errors = {}, {}

    def fetch(member):
        ticker, symbol, isin = member
        try:
            data = client.fundamentals(symbol) or {}
            general = data.get("General") or {}
            if general.get("Code") != ticker or general.get("Exchange") != "NSE":
                raise ValueError("security identity mismatch")
            if isin and general.get("ISIN") and isin != general["ISIN"]:
                aliases = FactSetClient.from_env().regional_ids([isin, general["ISIN"]])
                if not aliases.get(isin) or aliases[isin] != aliases.get(general["ISIN"]):
                    raise ValueError("ISIN mismatch")
            return ticker, values(data), None
        except Exception as exc:
            return ticker, {}, type(exc).__name__

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(fetch, m) for m in members]
        for future in as_completed(futures):
            ticker, metrics, error = future.result()
            if error:
                errors[ticker] = error
                continue
            if metrics:
                rows = [dict(ticker=ticker, metric=k, value=v, effective_date=observed,
                             known_date=observed, source="eodhd", fiscal_period=f"snapshot:{observed}")
                        for k, v in metrics.items()]
                with sync_engine().begin() as conn:
                    conn.execute(insert(table).values(rows).on_conflict_do_nothing())
                for k in metrics:
                    counts[k] = counts.get(k, 0) + 1
    print(json.dumps(dict(requested=len(members), fields=counts, errors=errors), sort_keys=True))


if __name__ == "__main__":
    main()
