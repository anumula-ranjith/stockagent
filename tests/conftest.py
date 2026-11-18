"""Pytest fixtures: isolated warehouse per test, no network."""

from __future__ import annotations

import os
from dataclasses import replace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine

from stock_agents.common import config as cfg_mod
from stock_agents.storage.postgres import database_url


@pytest.fixture(autouse=True)
def _isolated_paths(tmp_path, monkeypatch):
    """Redirect data_dir / duckdb / logs to tmp so tests never touch real data."""
    cfg_mod.load_settings.cache_clear()
    settings = cfg_mod.load_settings()
    # Rebuild a frozen Settings with tmp paths.
    new_paths = cfg_mod.Paths(
        data_dir=tmp_path / "data",
        raw_dir=tmp_path / "data" / "raw",
        duckdb=tmp_path / "data" / "market.duckdb",
        backtests_dir=tmp_path / "backtests",
        log_dir=tmp_path / "logs",
        fixtures_dir=settings.paths.fixtures_dir,
    )
    for p in (new_paths.data_dir, new_paths.raw_dir, new_paths.backtests_dir, new_paths.log_dir):
        p.mkdir(parents=True, exist_ok=True)
    new_settings = replace(settings, paths=new_paths)
    monkeypatch.setattr(cfg_mod, "load_settings", lambda: new_settings)
    yield new_settings


@pytest.fixture
def postgres_url(monkeypatch):
    value = os.getenv("TEST_DATABASE_URL")
    if not value:
        pytest.skip("Set TEST_DATABASE_URL to a PostgreSQL instance for integration tests")
    url = database_url("psycopg2", value)
    name = f"test_stock_agents_{uuid4().hex}"
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.exec_driver_sql(f"CREATE DATABASE {name}")
    testing_url = url.set(database=name).render_as_string(hide_password=False)
    monkeypatch.setenv("DATABASE_URL", testing_url)
    try:
        yield testing_url
    finally:
        with admin.connect() as conn:
            conn.exec_driver_sql(f"DROP DATABASE {name} WITH (FORCE)")
        admin.dispose()


@pytest.fixture
def auth_database(postgres_url):
    root = cfg_mod.project_root()
    engine = create_engine(database_url("psycopg2", postgres_url))
    try:
        with engine.begin() as target:
            target.exec_driver_sql((root / "scripts/sql/init.sql").read_text(encoding="utf-8"))
        command.upgrade(Config(str(root / "alembic.ini")), "head")
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def rq_test_queue(monkeypatch):
    from fakeredis import FakeRedis
    from rq import Queue
    from rq.serializers import JSONSerializer

    from stock_agents.api import rq_dashboard
    from stock_agents.jobs import queue
    from stock_agents.storage import s3

    redis = FakeRedis()
    test_queue = Queue(queue.QUEUE_NAME, connection=redis, serializer=JSONSerializer)
    monkeypatch.setattr(queue, "rq_queue", lambda: test_queue)
    monkeypatch.setattr(rq_dashboard, "rq_queue", lambda: test_queue)
    monkeypatch.setattr(rq_dashboard.web, "from_url", lambda *args, **kwargs: (None, redis))
    monkeypatch.setattr(s3, "put_backtest", lambda job_id, summary, when: f"backtests/{job_id}")
    monkeypatch.setattr(s3, "presigned_url", lambda key: f"https://objects.example.com/{key}")
    rq_dashboard._dashboard.cache_clear()
    yield test_queue
    rq_dashboard._dashboard.cache_clear()
    redis.close()
