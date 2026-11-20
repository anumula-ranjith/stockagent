"""Authenticated, read-only alternative datasets; never convert missing data to zero."""

from datetime import UTC, date, datetime

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from stock_agents.api.auth import CurrentUser
from stock_agents.ingest.company_news import boundaries, normalize_symbol
from stock_agents.jobs.queue import sync_engine

router = APIRouter(prefix="/market-signals", tags=["market-signals"])


def read_signals(ticker, start, end, engine=None):
    ticker = normalize_symbol(ticker)
    if start > end or (end - start).days > 366:
        raise HTTPException(422, "Choose an inclusive range of at most 367 days")
    lo, hi = boundaries(start, end)
    params = dict(ticker=ticker, start=start, end=end, lo=lo, hi=hi)
    with (engine or sync_engine()).connect() as c:
        if not c.scalar(text("SELECT 1 FROM symbology WHERE ticker=:ticker"), params):
            raise HTTPException(404, "Unknown NSE symbol")

        def rows(sql):
            return [
                {k: v.astimezone(UTC) if isinstance(v, datetime) else v for k, v in r.items()}
                for r in c.execute(text(sql), params).mappings()
            ]

        result = dict(
            ticker=ticker,
            start=start,
            end=end,
            timezone="Asia/Kolkata",
            membership_basis="current_snapshot_backfill",
            short_sales=rows(
                "SELECT * FROM short_sale_observations WHERE ticker=:ticker AND trade_date BETWEEN :start AND :end ORDER BY trade_date DESC"
            ),
            short_interest=rows(
                "SELECT * FROM short_interest_estimates WHERE ticker=:ticker AND observation_date BETWEEN :start AND :end ORDER BY observation_date DESC"
            ),
            publisher_buzz=rows("""SELECT b.*,n.title,n.source AS publisher,n.url,n.published_at,
                ARRAY(SELECT ticker FROM publisher_buzz_companies WHERE news_item_id=b.news_item_id ORDER BY ticker) AS companies
                FROM publisher_buzz b JOIN news_items n ON n.id=b.news_item_id
                JOIN publisher_buzz_companies m ON m.news_item_id=b.news_item_id
                WHERE m.ticker=:ticker AND n.published_at>=:lo AND n.published_at<:hi ORDER BY n.published_at DESC"""),
            public_social_posts=rows("""SELECT p.*,'Hacker News' AS source,
                ARRAY(SELECT ticker FROM public_social_post_companies WHERE hn_item_id=p.hn_item_id ORDER BY ticker) AS companies
                FROM public_social_posts p JOIN public_social_post_companies m USING(hn_item_id)
                WHERE m.ticker=:ticker AND p.published_at>=:lo AND p.published_at<:hi ORDER BY p.published_at DESC"""),
            coverage=rows("""SELECT DISTINCT ON(source) source,start_date,end_date,status,started_at,finished_at,
                rows_fetched,rows_inserted,rows_updated,reason,snapshot_id,membership_basis,
                details->:ticker AS ticker_reason,
                CASE WHEN details->'_not_requested' ? :ticker THEN true ELSE false END AS ticker_not_requested,
                (start_date<=:start AND end_date>=:end) AS covers_requested_window
                FROM market_signal_runs WHERE source<>'universe' AND (ticker IS NULL OR ticker=:ticker)
                AND start_date<=:end AND end_date>=:start ORDER BY source,started_at DESC"""),
            notes=[
                "No row means no collected observation, not zero.",
                "Publisher buzz is headline coverage; HN is one public network.",
                "Coverage describes overlapping ingestion runs; inspect covers_requested_window and ticker reasons.",
            ],
        )
        from stock_agents.ingest.market_signals import SOURCES

        observed = {r["source"] for r in result["coverage"]}
        result["coverage"].extend(
            dict(
                source=s,
                status="not_run",
                reason="No overlapping source attempt",
                covers_requested_window=False,
            )
            for s in SOURCES
            if s not in observed
        )
        return result


@router.get("/{ticker}")
def signals(ticker: str, start: date, end: date, _user: CurrentUser):
    return read_signals(ticker, start, end)
