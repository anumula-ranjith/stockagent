from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import insert, select

from stock_agents.ingest.adjustments import adjusted_closes, refresh_adjustments
from stock_agents.ingest.daily import _write_prices
from stock_agents.storage.postgres import Base


def test_cash_and_split_adjust_only_earlier_sessions():
    days = [date(2026, 11, day) for day in (3, 4, 5)]
    prices = [dict(date=day, close=close) for day, close in zip(days, (100., 90., 45.), strict=True)]
    actions = [dict(ex_date=days[1], action_type="distribution", value=2., previous_close=100.),
               dict(ex_date=days[2], action_type="split", value=2.)]
    assert adjusted_closes(prices, actions, days[-1]) == dict(zip(days, (49., 45., 45.), strict=True))


def test_no_events_preserves_raw_closes_and_bonus_restates_history():
    days = [date(2026, 11, day) for day in (3, 4)]
    prices = [dict(date=day, close=close) for day, close in zip(days, (100., 50.), strict=True)]
    assert adjusted_closes(prices, [], days[-1]) == dict(zip(days, (100., 50.), strict=True))
    action = dict(ex_date=days[1], action_type="bonus", value=1.)
    assert adjusted_closes(prices, [action], days[-1]) == dict(zip(days, (50., 50.), strict=True))


@pytest.mark.parametrize("actions", [
    [dict(action_type="demerger", value=1.)],
    [dict(action_type="dividend", value=101.)],
    [dict(action_type="dividend", value=2.)] * 2,
    [dict(action_type="dividend", value=2.), dict(action_type="split", value=2.)],
    [dict(action_type="dividend", value=2.), dict(action_type="distribution", value=3.)],
])
def test_ambiguous_or_invalid_actions_cannot_create_adjusted_prices(actions):
    start, end = date(2026, 11, 4), date(2026, 11, 5)
    with pytest.raises(ValueError):
        adjusted_closes([dict(date=start, close=100.), dict(date=end, close=99.)],
                        [{**action, "ex_date": end, "previous_close": 100.} for action in actions], end)


def test_cash_requires_verified_previous_close_despite_existing_price_history():
    first, end = date(2026, 11, 5), date(2026, 11, 18)
    prices = [dict(date=first, close=90.), dict(date=end, close=98.)]
    action = dict(ex_date=end, action_type="dividend", value=2.)
    with pytest.raises(ValueError, match="verified pre-ex-date close"):
        adjusted_closes(prices, [action], end)
    # The actual previous session closed at 100; the retained 90 is stale.
    assert adjusted_closes(prices, [{**action, "previous_close": 100.}], end)[first] == 88.2


def test_postgres_backfill_restatement_and_source_failure_preserve_verified_data(auth_database):
    # Synthetic prices exercise the real four-symbol fallback/source arrangement.
    first, ex_date, last = date(2026, 11, 4), date(2026, 11, 5), date(2026, 11, 18)
    tickers = {"BAGMANE", "BIRET", "CMPDI", "HEGAM"}
    prices = Base.metadata.tables["prices_daily"]
    final_close = {"BAGMANE": 105.96, "BIRET": 319.76, "CMPDI": 181.18, "HEGAM": 267.59}
    events = {
        "BAGMANE": [dict(ex_date=ex_date, action_type="distribution", value=1.55)],
        "BIRET": [dict(ex_date=ex_date, action_type="distribution", value=5.7)],
        "CMPDI": [], "HEGAM": [],
    }
    nse = SimpleNamespace(corporate_actions=lambda ticker, *args: events[ticker],
                          previous_closes=lambda day: {t: dict(close=100., isin="INE000000001")
                                                       for t in tickers})
    with auth_database.begin() as conn:
        conn.execute(insert(Base.metadata.tables["symbology"]),
                     [dict(ticker=t, isin="INE000000001", active=True) for t in tickers])
        rows = [dict(ticker=t, date=day, open=100., high=400., low=50., close=closing,
                     adj_close=123. if t == "BIRET" and day == ex_date else None,
                     volume=10, known_date=first,
                     source="eodhd" if t == "BIRET" and day == ex_date else "nse_bhavcopy")
                for t in tickers for day, closing in ((first, 100.), (ex_date, 99.), (last, final_close[t]))]
        conn.execute(insert(prices), rows)
        result = refresh_adjustments(conn, nse, last, tickers)
        assert result["rows_written"] == 11
        assert result["errors"] == []
        actual = {(r.ticker, r.date): r.adj_close for r in conn.execute(select(prices))}
        assert actual["BAGMANE", first] == 98.45
        assert actual["BIRET", first] == 94.3
        assert actual["BIRET", ex_date] == 123.  # Vendor adjustment remains untouched.
        assert all(actual[t, last] == final_close[t] for t in tickers)
        assert refresh_adjustments(conn, nse, last, tickers)["rows_written"] == 0

        # A new action must restate existing non-null fallback history too.
        events["BAGMANE"].append(dict(ex_date=last, action_type="distribution", value=1.))
        assert refresh_adjustments(conn, nse, last, tickers)["rows_written"] == 2
        assert conn.scalar(select(prices.c.adj_close).where(
            prices.c.ticker == "BAGMANE", prices.c.date == first)) == 97.4655

        # A same-day raw-price retry followed by source failure retains verified values.
        original = {(r.ticker, r.date): (r.adj_close, r.known_date) for r in conn.execute(select(prices))}
        incoming = [{**row, "known_date": last + timedelta(days=1)} for row in rows
                    if row["source"] == "nse_bhavcopy"]
        assert _write_prices(conn, incoming) == 0
        def unavailable(*args):
            raise RuntimeError("NSE source unavailable")
        nse.corporate_actions = unavailable
        failure = refresh_adjustments(conn, nse, last, tickers)
        assert len(failure["errors"]) == 4
        assert failure["rows_written"] == 0
        after = {(r.ticker, r.date): (r.adj_close, r.known_date) for r in conn.execute(select(prices))}
        assert after == original

