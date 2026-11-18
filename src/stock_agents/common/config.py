"""Load config/settings.yaml, config/weights.yaml and .env.

Everything the rest of the code needs about where things live, how often to
rebalance, cost assumptions, and factor weights goes through here. No other
module should read YAML or environment variables directly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


def project_root() -> Path:
    """The stock-agents/ directory (two levels up from this file)."""
    return Path(__file__).resolve().parents[3]


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@dataclass(frozen=True)
class Paths:
    data_dir: Path
    raw_dir: Path
    duckdb: Path
    backtests_dir: Path
    log_dir: Path
    fixtures_dir: Path


@dataclass(frozen=True)
class Settings:
    raw: dict[str, Any]
    weights: dict[str, Any]
    paths: Paths
    timezone: str
    market_calendar: str
    exchange_suffix: str
    base_currency: str
    universe_seed_csv: str

    def env(self, key: str, default: str | None = None) -> str | None:
        return os.environ.get(key, default)


def _resolve(p: str, root: Path) -> Path:
    q = Path(p)
    return q if q.is_absolute() else (root / q)


@lru_cache(maxsize=1)
def load_settings() -> Settings:
    """Load settings.yaml + weights.yaml + .env. Cached for process lifetime."""
    root = project_root()
    load_dotenv(root / ".env", override=False)

    settings_raw = _read_yaml(root / "config" / "settings.yaml")
    weights_raw = _read_yaml(root / "config" / "weights.yaml")
    paths_raw = settings_raw.get("paths", {})
    paths = Paths(
        data_dir=_resolve(paths_raw["data_dir"], root),
        raw_dir=_resolve(paths_raw["raw_dir"], root),
        duckdb=_resolve(paths_raw["duckdb"], root),
        backtests_dir=_resolve(paths_raw["backtests_dir"], root),
        log_dir=_resolve(paths_raw["log_dir"], root),
        fixtures_dir=_resolve(paths_raw["fixtures_dir"], root),
    )
    for p in (paths.data_dir, paths.raw_dir, paths.backtests_dir, paths.log_dir):
        p.mkdir(parents=True, exist_ok=True)

    return Settings(
        raw=settings_raw,
        weights=weights_raw,
        paths=paths,
        timezone=settings_raw.get("timezone", "America/New_York"),
        market_calendar=settings_raw.get("market_calendar", "XNYS"),
        exchange_suffix=settings_raw.get("exchange_suffix", ".US"),
        base_currency=settings_raw.get("base_currency", "USD"),
        universe_seed_csv=settings_raw.get("universe", {}).get(
            "seed_csv", "config/universe_seed.csv"
        ),
    )


def reset_settings_cache() -> None:
    """Drop the cached settings (useful in tests with a custom config dir)."""
    load_settings.cache_clear()
