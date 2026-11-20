"""Celery services: a control queue stays responsive during long ingestion jobs."""
from datetime import UTC, datetime
from threading import Event, Thread
import os

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_ready, worker_shutdown

from stock_agents.common.config import load_settings
from stock_agents.jobs.queue import redis_url

load_settings()
app = Celery("quantora", broker=redis_url())
app.conf.update(
    timezone="Asia/Kolkata", enable_utc=True,
    task_serializer="json", accept_content=["json"], result_serializer="json",
    task_ignore_result=True, task_acks_late=True, task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1, broker_connection_retry_on_startup=True,
    task_soft_time_limit=6900, task_time_limit=7200,
    broker_connection_timeout=3, broker_transport_options={"visibility_timeout": 14400, "socket_connect_timeout": 3, "socket_timeout": 5},
    task_routes={"quantora.tick": {"queue": "quantora-control"}, "quantora.execute": {"queue": "quantora-pipelines"}, "quantora.company_news": {"queue": "quantora-news"}, "quantora.news_directory": {"queue": "quantora-news"}, "quantora.market_signals": {"queue": "quantora-pipelines"}},
    beat_schedule={
        "daily-paper-portfolios": {"task": "quantora.daily_picks", "schedule": crontab(minute="*/15"),
                                  "options": {"queue": "quantora-pipelines", "expires": 900}},
        "market-signals-universe": {"task": "quantora.market_signals", "schedule": crontab(hour=6, minute=20), "args": ["sync"], "options": {"queue": "quantora-pipelines", "expires": 3600}},
        "market-signals-morning": {"task": "quantora.market_signals", "schedule": crontab(hour=7, minute=10), "options": {"queue": "quantora-pipelines", "expires": 7200}},
        "market-signals-evening": {"task": "quantora.market_signals", "schedule": crontab(hour=18, minute=40), "options": {"queue": "quantora-pipelines", "expires": 7200}},
        "company-nse-filings": {"task": "quantora.company_news", "schedule": float(os.getenv("COMPANY_NEWS_NSE_SECONDS", "300")), "args": ["nse"], "options": {"expires": 300}},
        "company-media-headlines": {"task": "quantora.company_news", "schedule": float(os.getenv("COMPANY_NEWS_MEDIA_SECONDS", "900")), "args": ["media"], "options": {"expires": 900}},
        "company-directory-daily": {"task": "quantora.news_directory", "schedule": crontab(hour=6, minute=15)},
        "morning-0700-ist": {"task": "quantora.tick", "schedule": crontab(hour=7, minute=0)},
        "evening-1830-ist": {"task": "quantora.tick", "schedule": crontab(hour=18, minute=30)},
        "recover-and-deliver": {"task": "quantora.tick", "schedule": 60.0},
    },
)

_stop = Event()


@worker_ready.connect
def worker_heartbeat(sender=None, **kwargs):
    queues = sender.task_consumer.queues if sender else []
    if not any(q.name == "quantora-pipelines" for q in queues):
        return
    _stop.clear()
    def pulse():
        from stock_agents.jobs.queue import _redis
        while not _stop.is_set():
            try:
                _redis(redis_url()).set("quantora:pipeline-worker-heartbeat", datetime.now(UTC).isoformat(), ex=90)
            except Exception:
                pass
            _stop.wait(20)
    Thread(target=pulse, daemon=True).start()


@worker_shutdown.connect
def stop_heartbeat(**kwargs):
    _stop.set()


@app.task(name="quantora.tick")
def reconcile():
    from stock_agents.jobs.pipelines import tick
    tick()


@app.task(name="quantora.execute")
def execute_pipeline(run_id):
    from uuid import UUID

    from stock_agents.jobs.pipelines import execute
    execute(str(UUID(run_id)))


@app.task(name="quantora.company_news")
def company_news_task(group="all", start=None, end=None):
    from datetime import date, timedelta
    from stock_agents.ingest.company_news import IST, ingest
    today=datetime.now(IST).date()
    scheduled = start is None and end is None
    lookback = 6 if scheduled else 1
    results = ingest(date.fromisoformat(start) if start else today-timedelta(days=lookback),
                     date.fromisoformat(end) if end else today, group, scheduled=scheduled)
    if group in ("all", "media"):
        from stock_agents.ingest.company_search import refresh_company_search
        search = refresh_company_search(limit=25)
        from stock_agents.ingest.free_sentiment import refresh_sentiment
        from stock_agents.jobs.queue import sync_engine
        with sync_engine().begin() as conn:
            sentiment = refresh_sentiment(conn)
        return {"sources": results, "company_search": search, "sentiment": sentiment}
    return results


@app.task(name="quantora.news_directory")
def news_directory_task():
    from stock_agents.ingest.company_news import refresh_directory
    return refresh_directory()


@app.task(name="quantora.market_signals")
def market_signals_task(command="incremental"):
    from datetime import timedelta
    from stock_agents.ingest.market_signals import IST, backfill, sync_constituents
    if command == "sync":
        return sync_constituents()
    if command != "incremental":
        raise ValueError("Unknown market signals command")
    today = datetime.now(IST).date()
    return backfill(today-timedelta(days=6), today)


@app.task(name="quantora.daily_picks")
def daily_picks_task():
    from stock_agents.engine.daily_picks import capture_due
    return {"saved": capture_due()}
