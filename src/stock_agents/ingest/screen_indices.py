"""Refresh Nifty index memberships independently of the price ingestion jobs."""

from datetime import date

from sqlalchemy import text

from stock_agents.ingest.daily import _membership
from stock_agents.jobs.queue import sync_engine
from stock_agents.sources.nse import NSEClient

# Label, official constituent CSV suffix, minimum number of names to accept.
INDEX_FILES = {
    "NIFTY50": ("Nifty 50", "50", 50),
    "NIFTYNEXT50": ("Nifty Next 50", "next50", 50),
    "NIFTY100": ("Nifty 100", "100", 100),
    "NIFTY200": ("Nifty 200", "200", 200),
    "NIFTYMIDCAP150": ("Nifty Midcap 150", "midcap150", 150),
    "NIFTYSMALLCAP250": ("Nifty Smallcap 250", "smallcap250", 250),
    "NIFTYBANK": ("Nifty Bank", "bank", 10),
    "NIFTYIT": ("Nifty IT", "it", 10),
    "NIFTYAUTO": ("Nifty Auto", "auto", 10),
    "NIFTYPHARMA": ("Nifty Pharma", "pharma", 10),
}
CAP_INDEX = {"large": "NIFTY100", "mid": "NIFTYMIDCAP150", "small": "NIFTYSMALLCAP250"}


def refresh_screen_indices() -> dict[str, int]:
    client = NSEClient()
    try:
        groups = {
            code: set(client.index_constituents(suffix, minimum))
            for code, (_, suffix, minimum) in INDEX_FILES.items()
        }
    finally:
        client.close()
    with sync_engine().begin() as conn:
        # Publish a complete set in one transaction, preserving the previous set on failure.
        conn.execute(text("SELECT pg_advisory_xact_lock(490122865)"))
        _membership(conn, groups, date.today())
    return {code: len(tickers) for code, tickers in groups.items()}


if __name__ == "__main__":
    print(refresh_screen_indices())
