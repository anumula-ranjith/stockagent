"""Load the universe seed CSV into the PostgreSQL warehouse.

Populates:
  - symbology       (ticker -> EODHD symbol)
  - classification  (ticker -> sector, industry)  effective_date = today, known_date = today
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from stock_agents.common import config as _config
from stock_agents.common.logging import get_logger
from stock_agents.storage.warehouse import Warehouse

log = get_logger(__name__)


def load_universe(conn: Warehouse, seed_csv: Path, exchange_suffix: str) -> int:
    """Return number of tickers loaded."""
    with seed_csv.open(encoding="utf-8-sig", newline="") as seed:
        rows = list(csv.DictReader(seed))
    today = date.today()
    sym_rows = [
        (r["ticker"], f"{r['ticker']}{exchange_suffix}", None, None, None, True, today)
        for r in rows
    ]
    conn.executemany(
        """INSERT INTO symbology
           (ticker, eodhd_symbol, factset_id, isin, cusip, active, updated_at)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT (ticker) DO UPDATE SET
               eodhd_symbol=EXCLUDED.eodhd_symbol, updated_at=EXCLUDED.updated_at""",
        sym_rows,
    )
    cls_rows = [
        (r["ticker"], today, today, r.get("sector"), r.get("industry"), "seed_csv") for r in rows
    ]
    conn.executemany(
        """INSERT INTO classification
           (ticker, effective_date, known_date, sector, industry, source)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT (ticker,effective_date,source) DO UPDATE SET
               sector=EXCLUDED.sector, industry=EXCLUDED.industry, known_date=EXCLUDED.known_date""",
        cls_rows,
    )
    return len(rows)


def main() -> int:
    s = _config.load_settings()
    from stock_agents.storage.warehouse import connect

    suffix = getattr(s, "exchange_suffix", ".NSE")
    seed = _config.project_root() / s.universe_seed_csv
    with connect() as conn:
        n = load_universe(conn, seed, suffix)
    log.info("universe loaded: %d tickers", n)
    print(f"Loaded {n} tickers into symbology + classification")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
