"""Read-only PostgreSQL evidence report; writes no database rows."""

import json
from datetime import date
from stock_agents.jobs.queue import sync_engine
from stock_agents.api.market_signals import read_signals
from sqlalchemy import text


def audit():
    engine = sync_engine()
    queries = {
        "short_sales": "SELECT count(*) records,count(DISTINCT ticker) tickers,min(trade_date) earliest,max(trade_date) latest FROM short_sale_observations",
        "short_interest": "SELECT count(*) records,count(DISTINCT ticker) tickers,min(observation_date) earliest,max(observation_date) latest FROM short_interest_estimates",
        "publisher_buzz": "SELECT count(DISTINCT b.news_item_id) records,count(DISTINCT m.ticker) tickers,min(n.published_at) earliest,max(n.published_at) latest FROM publisher_buzz b JOIN news_items n ON n.id=b.news_item_id LEFT JOIN publisher_buzz_companies m USING(news_item_id)",
        "public_social_posts": "SELECT count(DISTINCT p.hn_item_id) records,count(DISTINCT m.ticker) tickers,min(p.published_at) earliest,max(p.published_at) latest FROM public_social_posts p LEFT JOIN public_social_post_companies m USING(hn_item_id)",
    }
    with engine.connect() as c:
        result = {
            "database": dict(
                c.execute(
                    text(
                        "SELECT current_database() AS database,inet_server_addr() AS host,inet_server_port() AS port,now() AS audited_at"
                    )
                )
                .mappings()
                .one()
            )
        }
        result["universe"] = dict(
            c.execute(
                text("SELECT * FROM research_universe_snapshots ORDER BY retrieved_at DESC LIMIT 1")
            )
            .mappings()
            .one()
        )
        result["datasets"] = {
            name: dict(c.execute(text(sql)).mappings().one()) for name, sql in queries.items()
        }
        result["latest_runs"] = [
            dict(r)
            for r in c.execute(
                text(
                    "SELECT DISTINCT ON(source) * FROM market_signal_runs ORDER BY source,started_at DESC"
                )
            ).mappings()
        ]
        result["paytm"] = read_signals("PAYTM.NS", date(2026, 11, 19), date(2026, 11, 19), engine)
    return result


if __name__ == "__main__":
    print(json.dumps(audit(), default=str, indent=2))
