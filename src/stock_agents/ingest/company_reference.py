"""Publish company names already present in the exchange reference files."""

from __future__ import annotations

import csv
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert

from stock_agents.common.config import load_settings, project_root
from stock_agents.jobs.queue import sync_engine
from stock_agents.sources.nse import NSEClient
from stock_agents.storage.postgres import CompanyReference, Symbology


def store_names(connection, nifty, fo, observed, *, include_seed=False) -> int:
    """Retain unmatched old tickers and update names only for corresponding securities."""
    symbols = dict(connection.execute(select(Symbology.ticker, Symbology.isin)).all())
    rows = {}
    for ticker in (nifty.keys() | fo.keys()) & symbols.keys():
        member = nifty.get(ticker, {})
        isin = member.get("isin") or symbols[ticker]
        if symbols[ticker] and isin != symbols[ticker]:
            continue
        name = member.get("name") or fo.get(ticker)
        if name:
            rows[ticker] = dict(
                ticker=ticker,
                company_name=name,
                isin=isin,
                venue="NSE",
                series=member.get("series"),
                source="nse_indices" if member else "nse_fo",
                observed_on=observed,
            )
    table = CompanyReference.__table__
    if include_seed:
        # Legacy seed identities can fill gaps without replacing an exchange identity.
        known = set(connection.scalars(select(table.c.ticker)))
        with (project_root() / load_settings().universe_seed_csv).open(
            encoding="utf-8-sig"
        ) as stream:
            for r in csv.DictReader(stream):
                ticker = r["ticker"]
                if (
                    ticker in symbols
                    and ticker not in rows
                    and ticker not in known
                    and r.get("name")
                ):
                    rows[ticker] = dict(
                        ticker=ticker,
                        company_name=r["name"],
                        isin=symbols[ticker],
                        venue=r["exchange"],
                        series=None,
                        source="seed_csv",
                        observed_on=observed,
                    )
    if not rows:
        return 0
    stmt = insert(table).values(list(rows.values()))
    fields = ["company_name", "isin", "venue", "series", "source"]
    stmt = stmt.on_conflict_do_update(
        index_elements=[table.c.ticker],
        set_={k: stmt.excluded[k] for k in [*fields, "observed_on"]},
        where=or_(*(table.c[k].is_distinct_from(stmt.excluded[k]) for k in fields)),
    )
    return connection.execute(stmt).rowcount


def refresh_company_reference():
    client = NSEClient()
    try:
        nifty, fo = client.nifty500(), client.fo_stocks()
    finally:
        client.close()
    with sync_engine().begin() as connection:
        return store_names(
            connection, nifty, fo, datetime.now(ZoneInfo("Asia/Kolkata")).date(), include_seed=True
        )


if __name__ == "__main__":
    print(f"Updated {refresh_company_reference()} company identities")
