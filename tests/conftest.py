"""Pytest fixtures: isolated warehouse per test, no network."""

from __future__ import annotations

from pathlib import Path

import pytest

from stock_agents.common import config as cfg_mod


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
        fixtures_dir=Path(settings.paths.fixtures_dir),
    )
    for p in (new_paths.data_dir, new_paths.raw_dir, new_paths.backtests_dir, new_paths.log_dir):
        p.mkdir(parents=True, exist_ok=True)
    new_settings = cfg_mod.Settings(
        raw=settings.raw,
        weights=settings.weights,
        paths=new_paths,
        timezone=settings.timezone,
        market_calendar=settings.market_calendar,
    )
    monkeypatch.setattr(cfg_mod, "load_settings", lambda: new_settings)
    yield new_settings
