"""Select the daily market price feed independently of account integrations."""

import json

from sqlalchemy import select

from stock_agents.common.config import load_settings
from stock_agents.storage.postgres import Base


def price_provider() -> str:
    name = load_settings().env("MARKET_PRICE_PROVIDER", "eodhd").strip().lower()
    if name not in {"eodhd", "angel_one"}:
        raise ValueError("MARKET_PRICE_PROVIDER must be eodhd or angel_one")
    return name


def angel_capture_result(connection, day) -> dict:
    """Read exactly the requested day's committed live capture."""
    log = Base.metadata.tables["run_log"]
    report = connection.scalar(select(log.c.warnings).where(log.c.run_id == f"angel-market-{day}"))
    if report is None:
        return {"status": "skipped", "trade_date": str(day), "reason": "No scheduled Angel One capture"}
    return json.loads(report)
