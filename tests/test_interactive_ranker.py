from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pandas as pd
from fastapi.testclient import TestClient

from stock_agents.api.auth import make_token
from stock_agents.api.main import app
from stock_agents.engine.ranker import RankSettings, score_book, to_payload
from stock_agents.engine.ranker_inputs import price_factors, snapshot_inputs
from stock_agents.engine.ranker_replay import Replay, replay
from stock_agents.storage.postgres import JobRun, User
from stock_agents.storage.schema import connect, init_schema


def test_price_factors_use_each_stocks_trading_sessions():
    dates = pd.bdate_range("2026-01-01", periods=75)
    rows = []
    for ticker in ("A", "B"):
        for i, day in enumerate(dates):
            if ticker == "B" and i == 65:
                continue  # A partial special session cannot break B's RSI.
            close = 100 + i + i % 3
            rows.append(dict(ticker=ticker, date=day.date(), adj_close=close,
                             close=close, high=close + 2, low=close - 2, volume=1000))
    factors = price_factors(pd.DataFrame(rows), pd.Index(["A", "B"], name="ticker"))
    assert pd.notna(factors.loc["B", "rsi14"])
    assert pd.notna(factors.loc["B", "vs_sma50"])
def test_tuning_changes_selection_and_withholds_licensed_raw_values():
    raw = pd.DataFrame(
        {
            "sector": ["Bank", "Bank", "Bank", "Bank"],
            "ret_1m": [0.1, 0.2, 0.3, 0.4],
            "ret_3m": [0.4, 0.3, 0.2, 0.1],
            "roe_ttm": [0.14, 0.16, 0.18, 0.22],
        },
        index=["A", "B", "C", "D"],
    )
    raw.attrs["protected"] = {"roe_ttm": {"A", "D"}}
    settings = RankSettings(factors={"ret_1m": 1, "roe_ttm": 1}, agents={"momentum": 1}, size=1)
    payload = to_payload(raw, settings, date(2026, 5, 1), date(2026, 5, 1))
    assert payload["books"]["combined"] == {"longs": ["D"], "shorts": ["A"]}
    assert "roe_ttm" not in payload["rows"]["D"]["values"]
    assert "fundamental" in payload["rows"]["D"]["values"]
    flip = settings.model_copy(update={"factors": {"ret_3m": 1}})
    assert score_book(raw, flip)[1]["combined"] == {"longs": ["A"], "shorts": ["D"]}
    assert score_book(raw, RankSettings(factors={}))[1]["combined"] == {"longs": [], "shorts": []}


def test_dated_membership_and_knowledge_separate_a_cohort_replay():
    start = date(2025, 1, 1)
    days = pd.bdate_range(start, periods=90).date.tolist()
    observed = days[-1]
    with connect(":memory:") as conn:
        init_schema(conn)
        for i, ticker in enumerate(["A", "B", "C", "D"]):
            conn.execute(
                "INSERT INTO index_membership VALUES ('NIFTY500',?,?,NULL,?)",
                [ticker, observed, observed],
            )
            rows = []
            for j, day in enumerate(days):
                price = 100 * (1 + (i - 1.5) * 0.001) ** j
                rows.append(
                    [
                        ticker,
                        day,
                        price,
                        price * 1.01,
                        price * 0.99,
                        price,
                        price,
                        1000,
                        "eodhd",
                        observed,
                    ]
                )
            conn.executemany("""INSERT INTO prices_daily
                (ticker,date,open,high,low,close,adj_close,volume,source,known_date)
                VALUES (?,?,?,?,?,?,?,?,?,?)""", rows)
        # A vendor flat bar on a market closure must never become a trading session.
        holiday = next(d + timedelta(days=1) for d in days[40:] if d.weekday() == 4)
        conn.execute(
            """INSERT INTO prices_daily
               (ticker,date,open,high,low,close,adj_close,volume,source,known_date)
               VALUES ('A',?,1,1,1,1,1,0,'eodhd',?)""", [holiday, observed]
        )
        conn.execute(
            "INSERT INTO fundamentals_pit VALUES ('A','roe_ttm','FY25',.2,?,?, 'eodhd')",
            [days[0], observed],
        )
        assert snapshot_inputs(conn, days[50])[0].empty
        cohort, _ = snapshot_inputs(conn, days[50], cohort_date=observed)
        assert len(cohort) == 4 and "roe_ttm" not in cohort
        cfg = Replay(
            end=observed,
            months=3,
            universe="current_cohort",
            settings=RankSettings(size=1, agents={"momentum": 1}, factors={"ret_1m": 1}),
        )
        report = replay(conn, cfg)
        assert report["rebalances"] >= 2 and report["total_return"] > 0
        assert str(holiday) not in {p["date"] for p in report["equity_curve"]}
        assert report["longs_last"] == ["D"] and report["shorts_last"] == ["A"]
        assert report["holdings_date"] is not None
        assert {row["ticker"] for row in report["holdings_last"]} == {"A", "D"}
        assert {row["side"] for row in report["holdings_last"]} == {"Long", "Short"}
        assert report["trades_latest"] and len(report["trades_latest"]) <= 40
        assert {row["action"] for row in report["trades_latest"]} <= {"Buy", "Sell", "Short", "Cover"}
        assert "error" in replay(conn, cfg.model_copy(update={"universe": "historical"}))
        assert (
            replay(conn, cfg.model_copy(update={"cost_bps": 100}))["total_return"]
            < report["total_return"]
        )


def test_latest_report_respects_ownership_and_legacy_shape(auth_database, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "isolated-ranker-report-test-secret-value")
    own, other, third = (str(uuid4()) for _ in range(3))
    now = datetime.now(UTC)
    with auth_database.begin() as conn:
        for i, user_id in enumerate((own, other, third)):
            conn.execute(User.__table__.insert().values(id=user_id, email=f"tester{i}@example.com"))
        for i, (owner, payload, data) in enumerate(
            [
                (None, {"start": "2025-01-01"}, {"note": "legacy"}),
                (None, {"ranker": {}}, {"study": "shared"}),
                (own, {"ranker": {}}, {"study": "own"}),
                (other, {"ranker": {}}, {"study": "private"}),
            ]
        ):
            conn.execute(
                JobRun.__table__.insert().values(
                    id=str(uuid4()),
                    user_id=owner,
                    job_type="backtest",
                    status="finished",
                    payload=payload,
                    result_data=data,
                    finished_at=now + timedelta(seconds=i),
                )
            )
    with TestClient(app) as client:

        def login(identifier):
            return {"Authorization": "Bearer " + make_token(identifier).access_token}

        assert client.get("/ranker/latest").status_code == 401
        assert client.get("/ranker/latest", headers=login(own)).json() == {"study": "own"}
        assert client.get("/ranker/latest", headers=login(third)).json() == {"study": "shared"}
        assert client.get("/backtest/latest", headers=login(own)).json() == {"note": "legacy"}
        assert (
            client.post(
                "/ranker/backtest", json={"end": "2025-01-01"}, headers=login(third)
            ).status_code
            == 403
        )
