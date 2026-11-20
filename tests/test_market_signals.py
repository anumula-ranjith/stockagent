import csv
import io
from datetime import date

import pytest

from stock_agents.ingest.market_signals import (
    parse_universe,
    parse_short_sales,
    parse_ortex,
    fetch_hn,
    buzz_title,
)


def test_universe_rejects_incomplete_and_duplicate_snapshots():
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Company Name", "Symbol", "ISIN Code", "Series"])
    for i in range(500):
        w.writerow([f"Company {i}", f"STOCK{i}", f"INE{i:09d}", "EQ"])
    assert len(parse_universe(out.getvalue().encode())) == 500
    with pytest.raises(ValueError):
        parse_universe(out.getvalue().splitlines()[0].encode())
    with pytest.raises(ValueError):
        parse_universe((out.getvalue() + out.getvalue().splitlines()[1] + "\n").encode())


def test_nse_uses_row_date_integer_quantity_and_missing_is_not_zero():
    payload = '\ufeff Date , Symbol , Security Name , Quantity \n19-Nov-2026,PAYTM,One97,"1,056"\n18-Nov-2026,INFY,Infosys,0\n'
    rows = parse_short_sales(payload.encode(), date(2026, 11, 18), date(2026, 11, 19))
    assert rows[0]["short_sale_shares"] == 1056 and rows[0]["trade_date"] == date(2026, 11, 19)
    assert rows[1]["short_sale_shares"] == 0
    with pytest.raises(ValueError):
        parse_short_sales(
            payload.replace("1,056", "1.5").encode(), date(2026, 11, 18), date(2026, 11, 19)
        )


def test_ortex_keeps_nulls_and_observation_dates():
    rows = parse_ortex(
        {"data": [{"date": "2026-11-19", "siShares": None, "siPctFreeFloat": 1.25}]},
        date(2026, 11, 1),
        date(2026, 11, 20),
    )
    assert (
        rows[0]["short_interest_shares"] is None
        and rows[0]["short_interest_pct_free_float"] == 1.25
    )
    assert (
        parse_ortex(
            {"data": [{"date": "2026-11-19", "siShares": None, "siPctFreeFloat": None}]},
            date(2026, 11, 1),
            date(2026, 11, 20),
        )
        == []
    )
    with pytest.raises(ValueError):
        parse_ortex(
            {"data": [{"date": "2026-11-19", "siShares": -1}]},
            date(2026, 11, 1),
            date(2026, 11, 20),
        )


def test_hn_splits_capped_windows_and_paginates():
    calls = []

    def fetch(params):
        calls.append(params)
        lo = int(params["numericFilters"].split(">=")[1].split(",")[0])
        hi = int(params["numericFilters"].split("<")[1])
        if hi - lo > 2:
            return {"nbHits": 1001, "nbPages": 1, "hits": []}
        page = params["page"]
        return {
            "nbHits": 2,
            "nbPages": 2,
            "hits": [
                {
                    "objectID": str(lo + page),
                    "created_at_i": lo + page,
                    "title": "Paytm launches new service",
                    "points": 2,
                    "num_comments": 3,
                }
            ],
        }

    rows = fetch_hn(100, 104, fetch)
    assert len(rows) == 4 and len(calls) == 5
    assert buzz_title("Paytm faces social media backlash")
    assert not buzz_title("Paytm quarterly financial results")


def test_company_matching_is_exact_and_multi_company():
    from stock_agents.ingest.company_news import company_aliases, matching_companies

    companies = [
        {"symbol": s, "aliases": company_aliases(s, n)}
        for s, n in [("PAYTM", "One 97 Communications Limited"), ("INFY", "Infosys Limited")]
    ]
    assert matching_companies("A payment platform", companies) == []
    assert set(matching_companies("Paytm and Infosys go viral", companies)) == {"PAYTM", "INFY"}


def test_local_postgres_engagement_and_transaction_rollback():
    """Real PostgreSQL write semantics, fabricated post rolled back (never production data)."""
    from datetime import UTC, datetime
    from sqlalchemy import text
    from stock_agents.jobs.queue import sync_engine
    from stock_agents.ingest.market_signals import store_posts

    engine = sync_engine()
    if engine.url.host not in ("localhost", "127.0.0.1") or not any(
        x in (engine.url.database or "") for x in ("local", "test")
    ):
        pytest.skip("Explicit local test database required")
    with engine.connect() as c:
        transaction = c.begin()
        try:
            rid = c.scalar(text("SELECT id FROM market_signal_runs LIMIT 1"))
            if not rid:
                pytest.skip("Apply migration and sync first")
            companies = [
                {"symbol": "PAYTM", "aliases": ["paytm"]},
                {"symbol": "INFY", "aliases": ["infosys"]},
            ]
            hit = {
                "objectID": "9223372036854775700",
                "title": "Paytm and Infosys fixture",
                "created_at_i": 1795046400,
                "points": 2,
                "num_comments": 3,
            }
            assert store_posts(c, [hit], companies, rid, datetime.now(UTC)) == (1, 0)
            assert store_posts(c, [hit], companies, rid, datetime.now(UTC)) == (0, 0)
            hit["points"] = 9
            hit["num_comments"] = 6
            assert store_posts(c, [hit], companies, rid, datetime.now(UTC)) == (0, 1)
            assert (
                c.scalar(
                    text(
                        "SELECT points FROM public_social_posts WHERE hn_item_id=9223372036854775700"
                    )
                )
                == 9
            )
            assert (
                c.scalar(
                    text(
                        "SELECT count(*) FROM public_social_post_companies WHERE hn_item_id=9223372036854775700"
                    )
                )
                == 2
            )
        finally:
            transaction.rollback()


def test_api_auth_validation_and_postgres_read():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from stock_agents.api.auth import get_current_user
    from stock_agents.api.market_signals import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    assert client.get("/market-signals/PAYTM?start=2026-11-19&end=2026-11-19").status_code == 401
    app.dependency_overrides[get_current_user] = lambda: object()
    assert client.get("/market-signals/PAYTM?start=2026-11-20&end=2026-11-19").status_code == 422
    assert (
        client.get("/market-signals/NOT_A_STOCK?start=2026-11-19&end=2026-11-19").status_code == 404
    )
    response = client.get("/market-signals/PAYTM.NS?start=2026-11-19&end=2026-11-19")
    assert response.status_code == 200
    assert response.json()["ticker"] == "PAYTM"
    assert (
        set(["short_sales", "short_interest", "publisher_buzz", "public_social_posts", "coverage"])
        <= response.json().keys()
    )


def test_invalid_sync_preserves_snapshot_and_missing_ortex_is_audited():
    from contextlib import contextmanager, nullcontext
    from types import SimpleNamespace
    from stock_agents.jobs.queue import sync_engine
    from stock_agents.ingest.market_signals import sync_constituents, current_universe, run_source

    engine = sync_engine()
    if engine.url.host not in ("localhost", "127.0.0.1") or "local" not in (
        engine.url.database or ""
    ):
        pytest.skip("Local integration database required")
    with engine.connect() as c:
        outer = c.begin()

        class TransactionEngine:
            @contextmanager
            def begin(self):
                with c.begin_nested():
                    yield c

            def connect(self):
                return nullcontext(c)

        wrapped = TransactionEngine()
        try:
            before = current_universe(wrapped)
            bad = SimpleNamespace(get=lambda *a: SimpleNamespace(content=b"not,a,valid,download"))
            with pytest.raises(ValueError):
                sync_constituents(wrapped, bad)
            assert current_universe(wrapped) == before
            from unittest.mock import patch

            with patch(
                "stock_agents.ingest.market_signals.load_settings",
                return_value=SimpleNamespace(env=lambda *a: None),
            ):
                result = run_source(
                    wrapped, "ortex", date(2026, 11, 19), date(2026, 11, 19), *before
                )
            assert result["status"] == "unavailable" and result["rows_inserted"] == 0
            assert "not configured" in result["reason"]

            class OrtexFixture:
                def __init__(self, budget):
                    self.used = 0

                def get(self, url, params, headers):
                    self.used += 1
                    assert headers["Ortex-Api-Key"] == "fixture-secret"
                    return SimpleNamespace(
                        json=lambda: {
                            "data": [
                                {"date": "2026-11-19", "siShares": 123, "siPctFreeFloat": None}
                            ],
                            "pagination": {"next": "page2" if params["page"] == 1 else None},
                        }
                    )

            with (
                patch("stock_agents.ingest.market_signals.Client", OrtexFixture),
                patch(
                    "stock_agents.ingest.market_signals.load_settings",
                    return_value=SimpleNamespace(
                        env=lambda key, *args: "fixture-secret" if key == "ORTEX_API_KEY" else "50"
                    ),
                ),
            ):
                result = run_source(
                    wrapped,
                    "ortex",
                    date(2026, 11, 19),
                    date(2026, 11, 19),
                    *before,
                    symbol="PAYTM",
                )
            assert result["status"] == "success" and result["rows_inserted"] == 1
            assert result["details"]["_requests"] == 2
        finally:
            outer.rollback()


def test_request_budget_and_auth_failures_never_leak_credentials(monkeypatch):
    from types import SimpleNamespace
    from stock_agents.ingest.market_signals import Client, BudgetExceeded, SourceUnavailable

    monkeypatch.setattr(
        "stock_agents.ingest.market_signals.requests.get",
        lambda *a, **k: SimpleNamespace(status_code=403, headers={}),
    )
    client = Client(1)
    with pytest.raises(SourceUnavailable, match="HTTP 403") as exc:
        client.get("https://api.ortex.com/", headers={"Ortex-Api-Key": "fixture-secret"})
    assert "fixture-secret" not in str(exc.value)
    with pytest.raises(BudgetExceeded):
        client.get("https://api.ortex.com/")


def test_busy_hn_second_cannot_silently_truncate():
    from stock_agents.ingest.market_signals import IncompleteWindow

    with pytest.raises(IncompleteWindow):
        fetch_hn(100, 101, lambda p: {"nbHits": 1001, "nbPages": 1, "hits": []})


def test_generic_names_and_unrelated_brands_are_not_stock_discussions():
    from stock_agents.ingest.market_signals import signal_companies, signal_matches

    pairs = [
        ("BBOX", "Black Box Limited"),
        ("MEDANTA", "Global Health Limited"),
        ("ETERNAL", "Eternal Limited"),
        ("ASTRAL", "Astral Limited"),
        ("VEDL", "Vedanta Limited"),
        ("NAVA", "Nava Limited"),
        ("BOSCHLTD", "Bosch Limited"),
    ]
    companies = signal_companies([dict(ticker=t, company_name=n) for t, n in pairs])
    for title in [
        "Black-Box Distillation",
        "Global health authorities report measles",
        "An Eternal Golden Braid",
        "Astral Python tools acquired",
        "Advaita Vedanta books",
        "Nava OS 1.0",
        "The Haber-Bosch process",
    ]:
        assert signal_matches(title, companies) == []
    assert signal_matches("Zomato and Blinkit results", companies) == ["ETERNAL"]
    assert signal_matches("Bosch to create semiconductor division", companies) == ["BOSCHLTD"]
    assert signal_matches("Medanta hospital expansion", companies) == ["MEDANTA"]
