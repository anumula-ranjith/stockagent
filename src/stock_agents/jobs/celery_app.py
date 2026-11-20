"""Celery services: a control queue stays responsive during long ingestion jobs."""
from datetime import UTC, datetime
from threading import Event, Thread

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
    task_routes={"quantora.tick": {"queue": "quantora-control"}, "quantora.execute": {"queue": "quantora-pipelines"}},
    beat_schedule={
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
