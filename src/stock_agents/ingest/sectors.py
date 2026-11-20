"""Broad research sectors derived from exchange industry observations.

This is an application mapping, not an exchange-provided GICS classification.
New observations are dated today; historical classifications are not rewritten.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import text

INDUSTRY_SECTORS = {
    "Automobile and Auto Components": "Consumer Discretionary",
    "Capital Goods": "Industrials",
    "Chemicals": "Materials",
    "Construction": "Industrials",
    "Construction Materials": "Materials",
    "Consumer Durables": "Consumer Discretionary",
    "Consumer Services": "Consumer Discretionary",
    "Diversified": "Diversified",
    "Fast Moving Consumer Goods": "Consumer Staples",
    "Financial Services": "Financials",
    "Healthcare": "Health Care",
    "Information Technology": "Information Technology",
    "Media Entertainment & Publication": "Communication Services",
    "Metals & Mining": "Materials",
    "Oil Gas & Consumable Fuels": "Energy",
    "Power": "Utilities",
    "Realty": "Real Estate",
    "Services": "Industrials",
    "Telecommunication": "Communication Services",
    "Textiles": "Consumer Discretionary",
}


def sector_for(industry, existing=None):
    return (existing or "").strip() or INDUSTRY_SECTORS.get((industry or "").strip())


def fill_missing_sectors(connection, observed):
    rows = connection.execute(text("""
        SELECT s.ticker,s.isin,c.sector,c.industry FROM symbology s
        LEFT JOIN LATERAL (
            SELECT sector,industry FROM classification WHERE ticker=s.ticker
              AND effective_date<=:day AND known_date<=:day
              AND lower(trim(source)) NOT LIKE 'factset%'
            ORDER BY effective_date DESC,known_date DESC,source LIMIT 1
        ) c ON true WHERE s.active
    """), {"day": observed}).mappings().all()
    additions, unresolved = [], []
    for row in rows:
        if (row["sector"] or "").strip():
            continue
        industry = row["industry"]
        # Verified against the exchange listing; identity guard avoids symbol reuse.
        # https://www.msei.in/markets/equity/get-quotes/default?symbol=UJJIVANSFB
        if row["ticker"] == "UJJIVANSFB" and row["isin"] == "INE551W01018" and not industry:
            industry = "Financial Services"
        sector = sector_for(industry)
        if sector:
            additions.append(dict(ticker=row["ticker"], sector=sector, industry=industry, day=observed))
        else:
            unresolved.append(row["ticker"])
    if additions:
        connection.execute(text("""
            INSERT INTO classification(ticker,effective_date,known_date,sector,industry,source)
            VALUES (:ticker,:day,:day,:sector,:industry,'industry_sector_map')
            ON CONFLICT(ticker,effective_date,source) DO UPDATE SET
                sector=excluded.sector,industry=excluded.industry,known_date=excluded.known_date
        """), additions)
    return {"filled": len(additions), "unresolved": unresolved}


if __name__ == "__main__":
    from stock_agents.jobs.queue import sync_engine

    with sync_engine().begin() as connection:
        print(fill_missing_sectors(connection, datetime.now(ZoneInfo("Asia/Kolkata")).date()))
