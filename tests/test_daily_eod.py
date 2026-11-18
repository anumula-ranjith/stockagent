from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select

from stock_agents.sources.nse import parse_bhavcopy, parse_fo_tickers, parse_nifty500


def test_fo_members_exclude_index_contracts():
    text = "Underlying,Symbol,Nov\nNifty 50,NIFTY,65\nDerivatives on Individual Securities,Symbol,Nov\nAlpha Ltd,ALPHA,100\n"
    assert parse_fo_tickers(text) == {"ALPHA": "Alpha Ltd"}


def test_nifty_snapshot_rejects_duplicate_symbols():
    text = "Company Name,Industry,Symbol,Series,ISIN Code\nAlpha,Tech,ALPHA,EQ,INE000000001\nBeta,Tech,ALPHA,EQ,INE000000002\n"
    with pytest.raises(ValueError, match="duplicate"):
        parse_nifty500(text)


def test_bhavcopy_rejects_wrong_date_and_preserves_missing_adjustment():
    header = "TradDt,TckrSymb,SctySrs,ISIN,OpnPric,HghPric,LwPric,ClsPric,TtlTradgVol\n"
    row = "2026-11-18,ALPHA,EQ,INE000000001,10,12,9,11,500\n"
    result = parse_bhavcopy(header + row, date(2026, 11, 18))
    assert result["ALPHA"]["adj_close"] is None
    assert result["ALPHA"]["close"] == 11
    with pytest.raises(ValueError, match="date"):
        parse_bhavcopy(header + row, date(2026, 11, 17))


def _fixtures():
    today = date.today()
    def bar(ticker):
        return dict(ticker=ticker, date=today, open=10., high=12., low=9., close=11.,
                    adj_close=None, volume=100, source="nse_bhavcopy", isin=ticker, series="EQ")
    nse = SimpleNamespace(
        bhavcopy=lambda day: {t: {**bar(t), "date": day} for t in ("ALPHA", "FOONLY")},
        nifty500=lambda: {"ALPHA": dict(name="Alpha", industry="Tech", isin="ALPHA", series="EQ")},
        fo_stocks=lambda: {"ALPHA": "Alpha", "FOONLY": "F&O Only"},
        corporate_actions=lambda *args: [],
    )
    client = SimpleNamespace(eod=lambda *args, **kwargs: [], splits=lambda symbol: [], dividends=lambda symbol: [])
    return nse, client, today


def test_refresh_union_and_idempotent_price_source_replacement(auth_database):
    from stock_agents.ingest.daily import refresh_eod
    from stock_agents.storage.postgres import Base

    nse, client, today = _fixtures()
    with auth_database.begin() as target:
        first = refresh_eod(target, today, nse=nse, client=client)
        assert first["union_stocks"] == 2
        assert first["status"] == "ok"
        assert first["missing_adjusted"] == []
        assert first["nse_adjustments"]["tickers"] == ["ALPHA", "FOONLY"]
    client.eod = lambda symbol, **kwargs: [dict(date=today.isoformat(), open=10., high=12., low=9.,
                                               close=11., adjusted_close=10.5, volume=100)]
    with auth_database.begin() as target:
        # Emulate NSE-only data imported outside a completed daily attempt.
        target.execute(delete(Base.metadata.tables["run_log"]))
        result = refresh_eod(target, today, nse=nse, client=client)
        assert not result["missing_adjusted"]
        rows = target.execute(select(Base.metadata.tables["prices_daily"])).mappings().all()
        latest = [row for row in rows if row["date"] == today]
        assert len(latest) == 2
        assert {row["source"] for row in latest} == {"eodhd"}
    with auth_database.begin() as target:
        again = refresh_eod(target, today, nse=nse, client=client)
        assert again["rows_written"] == 0
    # An unavailable vendor response must retain existing adjusted prices.
    client.eod = lambda *args, **kwargs: []
    with auth_database.begin() as target:
        fallback = refresh_eod(target, today, nse=nse, client=client)
        assert fallback["missing_adjusted"] == []
        assert fallback["rows_written"] == 0


def test_incomplete_exchange_coverage_aborts_before_writes(auth_database):
    from stock_agents.ingest.daily import refresh_eod
    from stock_agents.storage.postgres import Base

    nse, client, today = _fixtures()
    nse.bhavcopy = lambda day: {}
    with auth_database.begin() as target:
        with pytest.raises(RuntimeError, match="missing universe symbols"):
            refresh_eod(target, today, nse=nse, client=client)
        assert target.execute(select(Base.metadata.tables["symbology"])).all() == []


def test_supported_vendor_lag_requests_retry_until_adjusted_close_arrives(auth_database):
    from stock_agents.ingest.daily import refresh_eod

    nse, client, today = _fixtures()
    def unavailable(*args):
        raise RuntimeError("NSE actions unavailable")
    nse.corporate_actions = unavailable
    previous = today - timedelta(days=1)
    client.eod = lambda symbol, **kwargs: [dict(date=previous.isoformat(), open=10., high=12.,
                                               low=9., close=11., adjusted_close=10.5, volume=100)]
    with auth_database.begin() as target:
        lagging = refresh_eod(target, today, nse=nse, client=client)
        assert lagging["status"] == "warning"
        assert lagging["missing_adjusted"] == ["ALPHA", "FOONLY"]
        assert {error["ticker"] for error in lagging["vendor_errors"]
                if error["error"] == "awaiting_adjusted_close"} == {"ALPHA", "FOONLY"}

    # A later empty vendor response still requests retry because history establishes coverage.
    client.eod = lambda *args, **kwargs: []
    with auth_database.begin() as target:
        assert refresh_eod(target, today, nse=nse, client=client)["status"] == "warning"

    client.eod = lambda symbol, **kwargs: [dict(date=today.isoformat(), open=10., high=12.,
                                               low=9., close=11., adjusted_close=10.5, volume=100)]
    nse.corporate_actions = lambda *args: []
    with auth_database.begin() as target:
        caught_up = refresh_eod(target, today, nse=nse, client=client)
        assert caught_up["status"] == "ok"
        assert caught_up["missing_adjusted"] == []


def test_same_day_retry_fetches_only_lagging_new_or_changed_stocks(auth_database):
    from stock_agents.ingest.daily import refresh_eod

    nse, client, today = _fixtures()
    def unavailable(*args):
        raise RuntimeError("NSE actions unavailable")
    nse.corporate_actions = unavailable
    original_bhav = nse.bhavcopy
    calls = []
    ready = {"ALPHA"}
    changed = set()

    def eod(symbol, **kwargs):
        ticker = symbol.removesuffix(".NSE")
        calls.append(("prices", ticker))
        day = today if ticker in ready else today - timedelta(days=1)
        closing = 12. if ticker in changed else 11.
        return [dict(date=day.isoformat(), open=10., high=12., low=9., close=closing,
                     adjusted_close=closing, volume=100)]

    client.eod = eod
    client.splits = lambda symbol: calls.append(("splits", symbol.removesuffix(".NSE"))) or []
    client.dividends = lambda symbol: calls.append(("dividends", symbol.removesuffix(".NSE"))) or []
    with auth_database.begin() as target:
        first = refresh_eod(target, today, nse=nse, client=client)
        assert first["vendor_tickers_requested"] == ["ALPHA", "FOONLY"]
    calls.clear()
    with auth_database.begin() as target:
        retry = refresh_eod(target, today, nse=nse, client=client)
        assert retry["vendor_tickers_requested"] == ["FOONLY"]
        assert len(calls) == 3
        assert {ticker for _, ticker in calls} == {"FOONLY"}

    def revised_bhav(day):
        rows = original_bhav(day)
        rows["ALPHA"]["close"] = 12.
        rows["NEW"] = {**rows["FOONLY"], "ticker": "NEW", "isin": "NEW"}
        return rows

    changed.add("ALPHA")
    ready.update(("FOONLY", "NEW"))
    nse.bhavcopy = revised_bhav
    nse.fo_stocks = lambda: {"ALPHA": "Alpha", "FOONLY": "F&O Only", "NEW": "New member"}
    nse.corporate_actions = lambda *args: []
    calls.clear()
    with auth_database.begin() as target:
        amended = refresh_eod(target, today, nse=nse, client=client)
        assert amended["vendor_tickers_requested"] == ["ALPHA", "FOONLY", "NEW"]
        assert amended["status"] == "ok"
        assert amended["union_stocks"] == 3
    calls.clear()
    with auth_database.begin() as target:
        complete = refresh_eod(target, today, nse=nse, client=client)
        assert complete["vendor_tickers_requested"] == []
        assert complete["status"] == "ok"
        assert calls == []
