"""Point-in-time read helpers.

Every agent and the backtest reads data **only** through these functions.
They enforce ``known_date <= t`` so no caller can accidentally use a fact that
was not yet published on date ``t``. Phase 2/3 fill in real implementations;
for Phase 0 these are stubs that raise ``NotImplementedError`` with a
pointer, so anything that imports them compiles.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import pandas as pd


def _nyi(what: str) -> None:
    raise NotImplementedError(f"pit.{what} is filled in during Phase 2/3")


def get_prices(t: date, tickers: Sequence[str], lookback_days: int) -> pd.DataFrame:
    _nyi("get_prices")


def get_universe(t: date) -> pd.DataFrame:
    _nyi("get_universe")


def get_fundamentals(t: date, tickers: Sequence[str]) -> pd.DataFrame:
    _nyi("get_fundamentals")


def get_estimates(t: date, tickers: Sequence[str]) -> pd.DataFrame:
    _nyi("get_estimates")


def get_news(t: date, tickers: Sequence[str], days: int = 7) -> pd.DataFrame:
    _nyi("get_news")


def get_short_interest(t: date, tickers: Sequence[str]) -> pd.DataFrame:
    _nyi("get_short_interest")


def get_insider_tx(t: date, tickers: Sequence[str], days: int = 90) -> pd.DataFrame:
    _nyi("get_insider_tx")


def get_events(t: date, tickers: Sequence[str], look_ahead_days: int = 5) -> pd.DataFrame:
    _nyi("get_events")


def get_macro(t: date, series_id: str) -> float | None:
    _nyi("get_macro")
