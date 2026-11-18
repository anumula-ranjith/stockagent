"""RQ worker: background jobs for heavy work (backtests, ingest).

Dev: `python -m stock_agents.jobs.worker`
Prod (docker-compose): started by the `worker` service.

Jobs are registered functions so RQ can look them up by dotted path.
Call sites enqueue with `enqueue_backtest(start, end, n)`.
"""

from __future__ import annotations

import logging
import os
from datetime import date
from typing import Any

import redis
from rq import Connection, Queue, Worker

QUEUE_NAME = "default"
HEAVY_QUEUE = "heavy"   # multi-minute backtests and bulk ingest


def _redis():
    return redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))


# --------------------------------------------------------------- job functions
def run_backtest_job(start: str, end: str, n: int, job_id: str) -> dict[str, Any]:
    """Executed inside the worker process. Runs the backtest and ships the
    summary JSON to S3.
    """
    from stock_agents.common import config as _config
    from stock_agents.engine.backtest import run_backtest
    from stock_agents.storage import schema
    from stock_agents.storage import s3 as _s3

    s = _config.load_settings()
    conn = schema.connect(str(s.paths.duckdb))
    try:
        summary = run_backtest(
            conn,
            start=date.fromisoformat(start),
            end=date.fromisoformat(end),
            n_per_side=n,
        )
    finally:
        conn.close()

    try:
        key = _s3.put_backtest(job_id, summary)
        summary["_s3_key"] = key
    except Exception as e:  # S3 is optional for local dev
        summary["_s3_error"] = str(e)
    return summary


def ingest_prices_job(years: int = 5, tickers: list[str] | None = None) -> dict[str, Any]:
    from stock_agents.common import config as _config
    from stock_agents.ingest.prices import backfill_prices
    from stock_agents.sources.eodhd import EODHDClient
    from stock_agents.storage import schema

    s = _config.load_settings()
    conn = schema.connect(str(s.paths.duckdb))
    try:
        schema.init_schema(conn)
        client = EODHDClient.from_env()
        n = backfill_prices(conn, client, years=years, tickers=tickers)
    finally:
        conn.close()
    return {"rows": n, "years": years, "tickers": tickers}


def compute_scores_job(asof: str | None = None) -> dict[str, int]:
    from stock_agents.common import config as _config
    from stock_agents.engine.scores import compute_and_store
    from stock_agents.storage import schema

    s = _config.load_settings()
    conn = schema.connect(str(s.paths.duckdb))
    try:
        schema.init_schema(conn)
        asof_date = date.fromisoformat(asof) if asof else None
        return compute_and_store(conn, asof=asof_date)
    finally:
        conn.close()


# ----------------------------------------------------- high-level API callers
def enqueue_backtest(start: str, end: str, n: int) -> str:
    """Enqueue and return the RQ job id. The API hands this back to the client."""
    q = Queue(HEAVY_QUEUE, connection=_redis(), default_timeout=1800)
    job = q.enqueue(
        "stock_agents.jobs.worker.run_backtest_job",
        args=(start, end, n),
        kwargs={"job_id": "pending"},  # overwritten below when id is known
    )
    # Attach the real job id so the function can route the S3 key
    job.meta["job_id"] = job.id
    job.save_meta()
    return job.id


def enqueue_ingest(years: int = 5, tickers: list[str] | None = None) -> str:
    q = Queue(HEAVY_QUEUE, connection=_redis(), default_timeout=7200)
    return q.enqueue("stock_agents.jobs.worker.ingest_prices_job", years, tickers).id


def enqueue_scores(asof: str | None = None) -> str:
    q = Queue(QUEUE_NAME, connection=_redis(), default_timeout=600)
    return q.enqueue("stock_agents.jobs.worker.compute_scores_job", asof).id


def job_status(job_id: str) -> dict[str, Any]:
    from rq.job import Job

    try:
        job = Job.fetch(job_id, connection=_redis())
    except Exception as e:
        return {"job_id": job_id, "status": "unknown", "error": str(e)}
    return {
        "job_id": job_id,
        "status": job.get_status(),
        "result": job.result if job.is_finished else None,
        "error": str(job.exc_info) if job.is_failed else None,
    }


# ------------------------------------------------------------------- entrypoint
def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
    log = logging.getLogger("worker")
    r = _redis()
    log.info("worker starting; listening on queues: %s, %s", HEAVY_QUEUE, QUEUE_NAME)
    with Connection(r):
        Worker([HEAVY_QUEUE, QUEUE_NAME]).work(with_scheduler=True)


if __name__ == "__main__":
    main()
