from datetime import date, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from stock_agents.api import auth, stock_profile
from stock_agents.ingest.company_reference import store_names
from stock_agents.storage.warehouse import Warehouse


def test_profile_requires_authentication():
    app = FastAPI()
    app.include_router(stock_profile.router)
    with TestClient(app) as client:
        assert client.get("/stock-profile/M%26M").status_code == 401


def test_company_name_refresh_matches_security_and_preserves_first_observation(auth_database):
    today = date.today()
    with auth_database.begin() as conn:
        conn.execute(text("INSERT INTO symbology(ticker,isin) VALUES ('A&B','ISIN-1')"))
        member = {"name": "A & B Ltd", "industry": "Autos", "series": "EQ", "isin": "ISIN-1"}
        assert store_names(conn, {"A&B": member}, {}, today) == 1
        assert store_names(conn, {"A&B": member}, {}, today + timedelta(days=1)) == 0
        assert (
            store_names(
                conn, {"A&B": {**member, "isin": "WRONG", "name": "Other company"}}, {}, today
            )
            == 0
        )
        assert conn.execute(
            text("select company_name,observed_on from company_reference")
        ).one() == ("A & B Ltd", today)


def test_exact_quote_membership_missing_coverage_and_privacy(auth_database):
    yesterday, today = date.today() - timedelta(days=1), date.today()
    tomorrow = today + timedelta(days=1)
    earlier = today - timedelta(days=40)
    with auth_database.begin() as conn:
        db = Warehouse(conn)
        db.execute(
            "INSERT INTO symbology(ticker,eodhd_symbol,isin) VALUES ('A&B','A&B.NSE','ISIN-1'),('OLD','OLD.NSE',NULL)"
        )
        db.executemany(
            "INSERT INTO prices_daily(ticker,date,close,volume,known_date,source) VALUES (?,?,?,?,?,?)",
            [
                ("A&B", today, 120, 100, today, "eodhd"),
                ("A&B", today, 150, 120, today, "nse_bhavcopy"),
                ("A&B", yesterday, 666, 250, today, "factset_formula"),
                ("A&B", yesterday, 160, 0, today, "nse_bhavcopy"),
                ("A&B", earlier, 100, 100, today, "nse_bhavcopy"),
                ("A&B", tomorrow, 123, 100, today, "eodhd"),
                ("A&B", yesterday, 555, 100, tomorrow, "eodhd"),
            ],
        )
        db.executemany(
            "INSERT INTO index_membership(index_code,ticker,joined_on,left_on,known_on) VALUES (?,?,?,?,?)",
            [
                ("NIFTY100", "A&B", yesterday, None, yesterday),
                ("NIFTY500", "A&B", yesterday, None, yesterday),
                ("NIFTYBANK", "A&B", yesterday, today, yesterday),
            ],
        )
        db.executemany(
            "INSERT INTO fundamentals_pit VALUES (?,?,?,?,?,?,?)",
            [
                ("A&B", "market_cap", "2026", 11e9, today, today, "eodhd"),
                ("A&B", "eps_ttm", "2026", 999, today, today, "factset_formula"),
            ],
        )
        db.execute(
            "INSERT INTO analyst_pit(ticker,rating_mean,effective_date,known_date,source) VALUES ('A&B',1.123,?,?,' FactSet')",
            [today, today],
        )
        db.execute(
            "INSERT INTO classification VALUES ('A&B',?,?,'PRIVATE','PRIVATE','factset_formula')",
            [today, today],
        )
        db.executemany(
            "INSERT INTO corporate_actions VALUES (?,?,?,?,?,?)",
            [("A&B", "split", today, 3, "nse", today), ("A&B", "split", today, 2, "eodhd", today)],
        )
        p = stock_profile.load_profile(db, "A&B", today)
        assert p.quote.close == 120 and p.quote.previous_date == earlier
        assert p.quote.change == 20 and p.quote.change_pct == 20
        assert p.cap_segment == "large" and [m.code for m in p.memberships] == [
            "NIFTY100",
            "NIFTY500",
        ]
        assert [(m.key, m.value, m.unit) for m in p.fundamentals] == [("market_cap", 11e9, "INR")]
        assert p.analyst == [] and p.sector is None and p.industry is None
        assert [(a.kind, a.value, a.source) for a in p.actions] == [("split", 3, "nse")]
        assert stock_profile.load_profile(db, "OLD", today).quote is None
    app = FastAPI()
    app.include_router(stock_profile.router)
    app.dependency_overrides[auth.get_current_user] = lambda: object()
    with TestClient(app) as client:
        assert client.get("/stock-profile/a%26b").json()["ticker"] == "A&B"
        assert client.get("/stock-profile/unknown").status_code == 404
