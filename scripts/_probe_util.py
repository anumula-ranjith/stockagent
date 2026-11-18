"""Shared helpers for probe scripts.

A probe:
  1. Loads credentials from .env (never hard-codes them).
  2. Calls one real endpoint with a known ticker / date.
  3. Prints the raw response so I can eyeball it.
  4. Saves the raw JSON gzipped under tests/fixtures/<source>_<endpoint>.json.gz.
  5. Returns a ProbeResult that scripts/run_all_probes.py can summarize.

Probes must not write to data/market.duckdb and must not import stock_agents.
"""

from __future__ import annotations

import gzip
import json
import os
import sys
import traceback
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Load .env from stock-agents/ root exactly once.
try:
    from dotenv import load_dotenv

    _ROOT = Path(__file__).resolve().parents[1]
    load_dotenv(_ROOT / ".env", override=False)
except ImportError:  # pragma: no cover
    _ROOT = Path(__file__).resolve().parents[1]

FIXTURES = _ROOT / "tests" / "fixtures"
FIXTURES.mkdir(parents=True, exist_ok=True)


@dataclass
class ProbeResult:
    source: str
    endpoint: str
    status: str  # 'ok' | 'skipped' | 'not_entitled' | 'error'
    http_status: int | None = None
    fixture: str | None = None
    fields: list[str] = field(default_factory=list)
    note: str = ""

    def as_row(self) -> str:
        fx = Path(self.fixture).name if self.fixture else "—"
        return f"{self.source:<18} {self.endpoint:<34} {self.status:<14} {fx}"


def require_env(*names: str) -> tuple[bool, str]:
    """Return (ok, missing_msg)."""
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        return False, f"missing env: {', '.join(missing)}"
    return True, ""


def save_fixture(source: str, endpoint: str, payload: Any) -> Path:
    """Save payload as a gzipped JSON fixture. Overwrites."""
    name = f"{source}_{endpoint}.json.gz".replace("/", "_")
    path = FIXTURES / name
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
    return path


def preview(obj: Any, max_chars: int = 1200) -> str:
    s = json.dumps(obj, indent=2, default=str)
    return s if len(s) <= max_chars else s[:max_chars] + f"\n... (+{len(s) - max_chars} chars)"


def top_level_keys(obj: Any) -> list[str]:
    if isinstance(obj, dict):
        return sorted(obj.keys())
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        return sorted(obj[0].keys())
    return []


def banner(title: str) -> None:
    print(f"\n{'=' * 8} {title} {'=' * (72 - len(title))}")


def run_and_summarize(name: str, fn) -> ProbeResult:
    banner(name)
    try:
        return fn()
    except Exception as e:  # pragma: no cover - probes are advisory
        traceback.print_exc()
        return ProbeResult(source=name, endpoint="?", status="error", note=str(e))


def utc_now() -> str:
    return datetime.now(tz=UTC).isoformat()


if __name__ == "__main__":  # pragma: no cover
    print("This module is a library used by scripts/probe_*.py")
    sys.exit(0)
