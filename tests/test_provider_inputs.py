from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from stock_agents.ingest import provider_inputs
from stock_agents.ingest.provider_values import eodhd_rows, number, ratio
from stock_agents.sources.factset import FORMULAS, FactSetClient


def test_eodhd_missing_sections_and_history_are_point_in_time():
    observed = date(2026, 11, 18)
    data = {
        "General": {"Code": "ABC", "Exchange": "NSE", "ISIN": "current"},
        "Highlights": {"DividendYield": 0, "ReturnOnEquityTTM": "NA"},
        "Valuation": "NA",
        "Earnings::Trend": "NA",
        "Earnings::History": {
            "reported": {"date": "2026-09-30", "reportDate": "2026-11-15", "surprisePercent": -8},
            "future": {"date": "2026-12-31", "reportDate": "2027-01-10", "surprisePercent": 5},
        },
    }
    rows = eodhd_rows("ABC", "current", data, observed)
    assert [(r["metric"], r["value"]) for r in rows["fundamentals_pit"]] == [("dividend_yield", 0)]
    assert rows["fundamentals_pit"][0]["known_date"] == observed
    assert rows["estimates_pit"] == []
    assert [r["known_date"] for r in rows["earnings_surprise"]] == [observed]
    data["General"]["ISIN"] = "old"
    with pytest.raises(ValueError, match="identity mismatch"):
        eodhd_rows("ABC", "current", data, observed, {"current": "C-R", "old": "O-R"})
    assert eodhd_rows("ABC", "current", data, observed, {"current": "C-R", "old": "C-R"}) == rows


def test_formula_maps_provider_order_currency_percentages_and_nulls(monkeypatch):
    raw = {
        "net_margin_ttm": 3,
        "_price": 12,
        "eps_ttm": 3,
        "market_cap": 50,
        "_annual_repurchases": 5,
        "_annual_issuance": 2,
        "rating_mean": 1.2,
        "_previous_rating": 1.5,
    }
    columns = {
        formula: {"result": [None, raw.get(metric)], "error": 0}
        for metric, (formula, _) in FORMULAS.items()
    }
    columns["P_CURRENCY"] = {"result": ["U.S. Dollar", "Indian Rupee"]}
    columns["requestId"] = {"result": ["US", "IN"]}
    response = SimpleNamespace(
        status_code=200,
        json=lambda: {
            "data": [{"dataItemName": name, **values} for name, values in columns.items()]
        },
    )
    monkeypatch.setattr("stock_agents.sources.factset.requests.post", lambda *a, **kw: response)
    client = FactSetClient("test", "test", "https://example.test")
    result = client.snapshot(["IN", "US"])
    assert result["US"] == {}
    assert result["IN"]["market_cap"] == 50_000_000
    assert result["IN"]["net_margin_ttm"] == 0.03
    assert result["IN"]["pe_ttm"] == 4
    assert result["IN"]["rating_change_1m"] == pytest.approx(0.3)
    assert result["IN"]["buyback_yield"] == pytest.approx(0.06)
    assert result["IN"]["fcf_yield"] is None
    assert ratio(20, 0) is None and number(float("nan")) is None


def test_batch_checkpoint_resumes_without_refetching_or_duplicates(auth_database, monkeypatch):
    day = date(2026, 11, 18)
    members = [("AAA", "first", "AAA.NSE"), ("BBB", "second", "BBB.NSE")]
    called = []

    def fetch(symbol):
        called.append(symbol)
        return {
            "General": {"Code": symbol.split(".")[0], "Exchange": "NSE"},
            "Highlights": {"PERatio": 20},
        }

    remaining = iter([110, 110])
    client = SimpleNamespace(remaining_calls=lambda: next(remaining), ranking_fundamentals=fetch)
    monkeypatch.setattr(provider_inputs.EODHDClient, "from_env", lambda: client)
    with auth_database.connect() as connection:
        connection.execute(text("INSERT INTO symbology(ticker) VALUES ('AAA'),('BBB')"))
        connection.commit()
        first = provider_inputs._load_provider(connection, "eodhd", members, day)
        assert first["status"] == "partial" and first["pending"] == ["BBB"]
        result = provider_inputs._load_provider(connection, "eodhd", members, day)
        assert result["status"] == "ok" and result["inserted"] == 2
        again = provider_inputs._load_provider(connection, "eodhd", members, day)
        assert again == result
        assert called == ["AAA.NSE", "BBB.NSE"]
        assert connection.scalar(text("SELECT count(*) FROM fundamentals_pit")) == 2
