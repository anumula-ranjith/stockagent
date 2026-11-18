"""CLI: init-db, load-universe, ingest-prices, ingest-corp-actions, ingest-bulk."""

from __future__ import annotations

import argparse
from datetime import date

from stock_agents.common import config as _config
from stock_agents.common.logging import configure, get_logger
from stock_agents.storage import schema


def _init_logging():
    s = _config.load_settings()
    configure(log_dir=str(s.paths.log_dir))
    return s, get_logger(__name__)


def _cmd_init_db(_args: argparse.Namespace) -> None:
    s, log = _init_logging()
    log.info("initializing warehouse at %s", s.paths.duckdb)
    conn = schema.connect()
    try:
        schema.init_schema(conn)
        tables = schema.list_tables(conn)
        log.info("done: %d tables", len(tables))
        print(f"Warehouse ready: {len(tables)} tables at {s.paths.duckdb}")
    finally:
        conn.close()


def _cmd_load_universe(_args: argparse.Namespace) -> None:
    from stock_agents.ingest.universe import load_universe

    s, log = _init_logging()
    conn = schema.connect()
    try:
        schema.init_schema(conn)
        seed = _config.project_root() / s.universe_seed_csv
        n = load_universe(conn, seed, s.exchange_suffix)
        print(f"Loaded {n} tickers from {seed}")
    finally:
        conn.close()


def _cmd_ingest_prices(args: argparse.Namespace) -> None:
    from stock_agents.ingest.prices import backfill_prices
    from stock_agents.sources.eodhd import EODHDClient

    s, log = _init_logging()
    conn = schema.connect()
    try:
        schema.init_schema(conn)
        client = EODHDClient.from_env()
        tickers = args.tickers.split(",") if args.tickers else None
        n = backfill_prices(conn, client, years=args.years, tickers=tickers)
        print(f"Price backfill done: {n} rows")
    finally:
        conn.close()


def _cmd_ingest_corp(args: argparse.Namespace) -> None:
    from stock_agents.ingest.prices import ingest_corporate_actions
    from stock_agents.sources.eodhd import EODHDClient

    s, log = _init_logging()
    conn = schema.connect()
    try:
        schema.init_schema(conn)
        client = EODHDClient.from_env()
        tickers = args.tickers.split(",") if args.tickers else None
        n = ingest_corporate_actions(conn, client, tickers=tickers)
        print(f"Corporate actions written: {n}")
    finally:
        conn.close()


def _cmd_ingest_bulk(args: argparse.Namespace) -> None:
    from stock_agents.ingest.prices import ingest_bulk_last_day
    from stock_agents.sources.eodhd import EODHDClient

    s, log = _init_logging()
    conn = schema.connect()
    try:
        schema.init_schema(conn)
        client = EODHDClient.from_env()
        td = date.fromisoformat(args.date) if args.date else None
        exch = args.exchange or s.exchange_suffix.lstrip(".")
        n = ingest_bulk_last_day(conn, client, exchange=exch, trade_date=td)
        print(f"Bulk ingest: {n} rows for {exch} ({td or 'latest'})")
    finally:
        conn.close()


def _cmd_ingest_news(args: argparse.Namespace) -> None:
    from stock_agents.ingest.news import ingest_news, ingest_sentiment_daily
    from stock_agents.sources.eodhd import EODHDClient

    s, log = _init_logging()
    conn = schema.connect()
    try:
        schema.init_schema(conn)
        client = EODHDClient.from_env()
        tickers = args.tickers.split(",") if args.tickers else None
        n1 = ingest_news(conn, client, tickers=tickers, limit_per_ticker=args.limit)
        n2 = ingest_sentiment_daily(conn, client, tickers=tickers)
        print(f"News: {n1} rows, sentiment_daily: {n2} rows")
    finally:
        conn.close()


def _cmd_compute_scores(args: argparse.Namespace) -> None:
    from stock_agents.engine.scores import compute_and_store

    s, log = _init_logging()
    conn = schema.connect()
    try:
        schema.init_schema(conn)
        asof = date.fromisoformat(args.asof) if args.asof else None
        counts = compute_and_store(conn, asof=asof)
        for name, n in counts.items():
            print(f"  {name}: {n} tickers scored")
    finally:
        conn.close()


def _cmd_combine(args: argparse.Namespace) -> None:
    from stock_agents.engine.combiner import combine_latest
    import json as _json

    s, log = _init_logging()
    conn = schema.connect()
    try:
        schema.init_schema(conn)
        out = combine_latest(conn, asof=args.asof, n_per_side=args.n, mode=args.mode)
        print(_json.dumps(out, indent=2, default=str))
    finally:
        conn.close()


def _cmd_backtest(args: argparse.Namespace) -> None:
    from stock_agents.engine.backtest import run_backtest

    s, log = _init_logging()
    conn = schema.connect()
    try:
        schema.init_schema(conn)
        out = run_backtest(
            conn,
            start=date.fromisoformat(args.start),
            end=date.fromisoformat(args.end),
            n_per_side=args.n,
        )
        print(
            f"BACKTEST {out.get('start')} to {out.get('end')}:\n"
            f"  total return:   {out.get('total_return', 0) * 100:+.2f}%\n"
            f"  annual return:  {out.get('annual_return', 0) * 100:+.2f}%\n"
            f"  annual vol:     {out.get('annual_vol', 0) * 100:.2f}%\n"
            f"  sharpe:         {out.get('sharpe', 0):.2f}\n"
            f"  max drawdown:   {out.get('max_drawdown', 0) * 100:.2f}%"
        )
    finally:
        conn.close()


def _cmd_status(_args: argparse.Namespace) -> None:
    s, log = _init_logging()
    conn = schema.connect()
    try:
        schema.init_schema(conn)
        tickers = conn.execute("SELECT COUNT(*) FROM symbology WHERE active = TRUE").fetchone()[0]
        prows = conn.execute("SELECT COUNT(*) FROM prices_daily").fetchone()[0]
        pmin, pmax = conn.execute("SELECT MIN(date), MAX(date) FROM prices_daily").fetchone()
        corp = conn.execute("SELECT COUNT(*) FROM corporate_actions").fetchone()[0]
        news = conn.execute("SELECT COUNT(*) FROM news").fetchone()[0]
        print(f"Universe:   {tickers} tickers")
        print(f"Prices:     {prows:,} rows, {pmin} to {pmax}")
        print(f"Corp act.:  {corp:,}")
        print(f"News:       {news:,}")
    finally:
        conn.close()


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="stock-agents")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db").set_defaults(func=_cmd_init_db)
    sub.add_parser("load-universe").set_defaults(func=_cmd_load_universe)
    sub.add_parser("status").set_defaults(func=_cmd_status)

    pp = sub.add_parser("ingest-prices", help="Per-ticker /eod backfill")
    pp.add_argument("--years", type=int, default=5)
    pp.add_argument("--tickers", type=str, default=None, help="Comma-separated subset")
    pp.set_defaults(func=_cmd_ingest_prices)

    pc = sub.add_parser("ingest-corp-actions", help="Splits + dividends per ticker")
    pc.add_argument("--tickers", type=str, default=None)
    pc.set_defaults(func=_cmd_ingest_corp)

    pb = sub.add_parser("ingest-bulk", help="Bulk EOD for one exchange, one day")
    pb.add_argument("--exchange", type=str, default=None, help="Default: from settings")
    pb.add_argument("--date", type=str, default=None, help="YYYY-MM-DD, default latest")
    pb.set_defaults(func=_cmd_ingest_bulk)

    pn = sub.add_parser("ingest-news", help="News + daily sentiment")
    pn.add_argument("--tickers", type=str, default=None)
    pn.add_argument("--limit", type=int, default=50)
    pn.set_defaults(func=_cmd_ingest_news)

    pcs = sub.add_parser("compute-scores", help="Compute all 4 agent scores as of today")
    pcs.add_argument("--asof", type=str, default=None)
    pcs.set_defaults(func=_cmd_compute_scores)

    pco = sub.add_parser("combine", help="Combine scores into longs/shorts")
    pco.add_argument("--asof", type=str, default=None)
    pco.add_argument("--n", type=int, default=10)
    pco.add_argument("--mode", type=str, default="weighted")
    pco.set_defaults(func=_cmd_combine)

    pbt = sub.add_parser("backtest", help="Run backtest")
    pbt.add_argument("--start", type=str, required=True, help="YYYY-MM-DD")
    pbt.add_argument("--end", type=str, required=True)
    pbt.add_argument("--n", type=int, default=10)
    pbt.set_defaults(func=_cmd_backtest)

    return p


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":  # pragma: no cover
    main()
