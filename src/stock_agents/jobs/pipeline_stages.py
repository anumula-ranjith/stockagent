"""Small stage adapters; raw vendor payloads never enter admin responses."""
from contextlib import contextmanager
from datetime import datetime, timedelta

from sqlalchemy import text

from stock_agents.common.config import load_settings
from stock_agents.ingest.price_provider import price_provider
from stock_agents.jobs.pipelines import TZ
from stock_agents.jobs.queue import sync_engine


@contextmanager
def warehouse_writer():
    with sync_engine().connect() as conn:
        locked = conn.scalar(text("SELECT pg_try_advisory_lock(490122862)"))
        conn.commit()
        if not locked:
            raise RuntimeError("Another warehouse writer is active")
        try:
            yield conn
            conn.commit()
        finally:
            conn.rollback()
            conn.execute(text("SELECT pg_advisory_unlock(490122862)"))
            conn.commit()


def coverage(day):
    with sync_engine().connect() as conn:
        rows = conn.execute(text("""
            SELECT s.ticker,c.sector,p.close,p.adj_close,p.volume
            FROM symbology s
            LEFT JOIN LATERAL (SELECT sector FROM classification c WHERE c.ticker=s.ticker
                AND known_date<=:today AND effective_date<=:today
                AND lower(trim(source)) NOT LIKE 'factset%'
                ORDER BY effective_date DESC,known_date DESC,source LIMIT 1) c ON true
            LEFT JOIN LATERAL (SELECT close,adj_close,volume FROM prices_daily p
                WHERE p.ticker=s.ticker AND p.date=:day AND known_date<=:today
                AND source IN ('angel_one','eodhd','nse_bhavcopy')
                ORDER BY (source='angel_one') DESC,(source='eodhd') DESC,known_date DESC LIMIT 1) p ON true
            WHERE s.active AND EXISTS (SELECT 1 FROM index_membership m
                WHERE m.ticker=s.ticker AND index_code IN ('NIFTY500','NSE_FO')
                AND joined_on<=:today AND known_on<=:today AND (left_on IS NULL OR left_on>:today))
            ORDER BY s.ticker
        """), {"day": day, "today": datetime.now(TZ).date()}).mappings().all()
    missing = [r["ticker"] for r in rows if r["close"] is None]
    invalid = [r["ticker"] for r in rows if r["close"] is not None and (r["close"] <= 0 or (r["volume"] or 0) < 0)]
    sectors = [r["ticker"] for r in rows if not (r["sector"] or "").strip()]
    adjusted = [r["ticker"] for r in rows if r["adj_close"] is None or r["adj_close"] <= 0]
    return {"trade_date": str(day), "members": len(rows), "priced": len(rows)-len(missing),
            "adjusted": len(rows)-len(adjusted), "missing_prices": missing,
            "missing_adjusted": adjusted, "missing_sectors": sectors, "invalid_prices": invalid,
            "status": "warning" if missing or adjusted or sectors or invalid else "ok"}


def summary(result):
    if not isinstance(result, dict):
        return {"status": "ok"}
    clean = {k: v for k, v in result.items() if isinstance(v, (int, float, bool)) or k in ("status", "date", "trade_date", "reason", "method", "fallback_reason")}
    for key in ("errors", "vendor_errors", "missing", "missing_adjusted", "unresolved", "failures"):
        if result.get(key):
            clean[key + "_count"] = len(result[key]) if isinstance(result[key], (list, dict, tuple)) else result[key]
            clean["status"] = "partial"
    if result.get("unavailable") or result.get("unmatched_volume"):
        clean["status"] = "partial"
    return clean


def run_stage(name, day):
    settings = load_settings()
    if name == "preflight":
        from stock_agents.jobs.queue import _redis, redis_url
        _redis(redis_url()).ping()
        with sync_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "database": True, "broker": True}
    if name == "validate":
        result = coverage(day)
        if not result["members"] or result["missing_prices"] or result["invalid_prices"]:
            raise RuntimeError("Required EOD prices are missing or invalid")
        return result
    if name == "publish":
        from stock_agents.jobs.queue import _redis, redis_url
        _redis(redis_url()).incr("quantora:market-generation")
        return {"status": "ok", "cache_refresh_requested": True}
    with warehouse_writer() as conn:
        if name == "reference":
            from stock_agents.ingest.company_reference import refresh_company_reference
            from stock_agents.ingest.screen_indices import refresh_screen_indices
            from stock_agents.ingest.sectors import fill_missing_sectors
            indices = refresh_screen_indices()
            if price_provider() == "angel_one":
                from stock_agents.ingest.daily import refresh_primary_reference
                reference = refresh_primary_reference(conn)
                return {"status": "partial" if reference["unresolved"] else "ok", "indices": len(indices), **reference}
            names = refresh_company_reference()
            sectors = fill_missing_sectors(conn, datetime.now(TZ).date())
            return {"status": "partial" if sectors["unresolved"] else "ok", "indices": len(indices), "names": names, **sectors}
        if name == "eod":
            if price_provider() == "angel_one":
                from stock_agents.ingest.angel_eod import refresh_angel_eod
                return summary(refresh_angel_eod(conn, day))
            from stock_agents.ingest.daily import refresh_eod
            return summary(refresh_eod(conn, trade_date=day))
        if name == "providers":
            from scripts.derive_peg import derive_peg
            from stock_agents.ingest.provider_inputs import refresh_provider_inputs
            result = refresh_provider_inputs(due=False)
            derive_peg()
            return summary(result)
        if name == "insider":
            from stock_agents.ingest.nse_insider import refresh_insider_filings
            return summary(refresh_insider_filings(days=7))
        if name == "short_selling":
            from stock_agents.ingest.nse_short_selling import refresh_short_selling
            return summary(refresh_short_selling(day-timedelta(days=7), day))
        if name == "news":
            from stock_agents.ingest.free_news import ingest_free_news
            result = ingest_free_news(conn)
            if result["status"] == "failed":
                result["status"] = "partial"
            # RSS remains independent of paid credentials and paid-source failures.
            if settings.env("EODHD_API_KEY"):
                from stock_agents.ingest.news import ingest_news
                from stock_agents.sources.eodhd import EODHDClient
                from stock_agents.storage.warehouse import Warehouse
                try:
                    with conn.begin_nested():
                        paid = ingest_news(Warehouse(conn), EODHDClient.from_env(), report=True)
                except Exception:
                    paid = {"status": "failed", "reason": "EODHD news unavailable"}
                result["eodhd"] = paid
                if paid["status"] != "ok" or result["status"] != "ok":
                    result["status"] = "partial"
            return result
        if name == "sentiment":
            if not settings.env("EODHD_API_KEY"):
                return {"status": "skipped", "reason": "EODHD source is not configured"}
            from stock_agents.ingest.news import ingest_news, ingest_sentiment_daily
            from stock_agents.sources.eodhd import EODHDClient
            from stock_agents.storage.warehouse import Warehouse
            action = ingest_news if name == "news" else ingest_sentiment_daily
            return action(Warehouse(conn), EODHDClient.from_env(), report=True)
        if name == "scores":
            from stock_agents.engine.scores import compute_and_store
            from stock_agents.storage.warehouse import Warehouse
            return summary(compute_and_store(Warehouse(conn), asof=day))
    raise ValueError("Unknown pipeline stage")
