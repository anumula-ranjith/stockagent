"""Minimal CLI. Only what Phase 0 needs: `init-db`. Grows per phase."""

from __future__ import annotations

import argparse

from stock_agents.common import config as _config
from stock_agents.common.logging import configure, get_logger
from stock_agents.storage import schema


def _cmd_init_db(_args: argparse.Namespace) -> None:
    s = _config.load_settings()
    configure(log_dir=str(s.paths.log_dir))
    log = get_logger(__name__)
    log.info("initializing warehouse at %s", s.paths.duckdb)
    conn = schema.connect()
    try:
        schema.init_schema(conn)
        tables = schema.list_tables(conn)
        log.info("done: %d tables (%s)", len(tables), ", ".join(tables[:4]) + ", ...")
    finally:
        conn.close()


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="stock-agents")
    sub = p.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("init-db", help="Create missing DuckDB tables")
    pi.set_defaults(func=_cmd_init_db)
    return p


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":  # pragma: no cover
    main()
