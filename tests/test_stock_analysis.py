from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from stock_agents.api import auth, ranker
from stock_agents.api.main import app
from stock_agents.engine.ranker import DEFAULT_FACTORS, RankSettings, score_book
from stock_agents.engine.stock_analysis import FACTOR_INFO, stock_analysis

DAY = date(2026, 11, 18)


def observations():
    frame = pd.DataFrame(
        {
            "sector": ["IT", "IT", "IT", "Steel", "Steel"],
            "rsi14": [60, 50, 40, 25, np.nan],
            "vs_sma50": [0.15, 0.05, 0.01, -0.03, -0.05],
            "vs_sma200": [0.2, 0.12, 0.03, -0.08, -0.11],
            "ret_1m": [0.11, 0.03, -0.01, -0.02, -0.04],
            "ret_6m": [0.14, 0.08, 0.02, -0.12, -0.2],
            "volatility": [0.15, 0.12, 0.06, 0.25, np.nan],
            "hot_sector": [0.10, 0.10, 0.10, -0.04, -0.04],
            "headlines": [10, 2, 0, 11, np.nan],
            "news_tone_7d": [0.45, -0.1, np.nan, 0.56, np.nan],
            "pe_ttm": [15, 25, 35, 9, -1],
            "roe_ttm": [0.17612763, 0.1325, 0.2223, 0.24, 0.19],
            "revenue_growth_yoy": [0.25, 0.2, 0.1, 0.2, np.nan],
        },
        index=["A", "B", "C", "D", "E"],
    )
    frame.attrs["protected"] = {"roe_ttm": {"A"}}
    return frame


def test_each_stock_reconciles_all_settings_and_evidence():
    raw = observations()
    settings = RankSettings(size=1, vol_adjust=True)
    frame, books = score_book(raw, settings)
    assert set(DEFAULT_FACTORS) == set(FACTOR_INFO)
    assert "C" not in books["combined"]["longs"] + books["combined"]["shorts"]
    for ticker in raw.index:
        out = stock_analysis(raw, settings, DAY, DAY, ticker)
        assert out["composite"]["score"] == frame.at[ticker, "composite"]
        assert out["composite"]["score"] == pytest.approx(
            50 + sum(a["composite_contribution"] or 0 for a in out["agents"])
        )
        for a in out["agents"]:
            values = frame[a["agent"]]
            side = a["selection"]["side"]
            if side:
                assert books[a["agent"]][side + "s"][a["selection"]["place"] - 1] == ticker
            if pd.isna(values[ticker]):
                assert a["score"] is None and a["rank"] is None and a["observed"] == 0
                continue
            assert a["score"] == pytest.approx(values[ticker])
            assert a["rank"] == int((values > values[ticker]).sum()) + 1
            assert a["score"] == pytest.approx(
                50 + (a["bonus"] or 0) + sum(f["contribution"] or 0 for f in a["factors"])
            )
            if a["strongest"]:
                driver = next(f for f in a["factors"] if f["key"] == a["strongest"])
                assert driver["contribution"] == max(f["contribution"] or 0 for f in a["factors"])
    a = stock_analysis(raw, settings, DAY, DAY, "a")
    fund = next(agent for agent in a["agents"] if agent["agent"] == "fundamental")
    roe = next(row for row in fund["factors"] if row["key"] == "roe_ttm")
    assert roe["status"] == "observed" and roe["restricted"] and roe["value"] is None
    assert (roe["peer_universe"], roe["peer_observations"]) == (3, 3)
    assert len(fund["pillars"]) == 5 and "0.17612763" not in str(a)


def test_missing_data_disabled_controls_and_nonmembers():
    raw = observations()
    cfg = RankSettings(factors={"pe_ttm": 1}, agents={"fundamental": 100})
    data = stock_analysis(raw, cfg, DAY, DAY, "E")
    assert data["composite"]["score"] is None
    fund = next(a for a in data["agents"] if a["agent"] == "fundamental")
    assert next(f for f in fund["factors"] if f["key"] == "pe_ttm")["status"] == "unscoreable"
    assert fund["observed"] == 0 and fund["enabled"] == 1
    technical = data["agents"][0]
    assert technical["score"] is None and technical["enabled"] == 0
    assert "agents" not in stock_analysis(raw, cfg, DAY, DAY, "OUTSIDE")
    assert stock_analysis(raw.iloc[0:0], cfg, DAY, None, "A")["universe"] == 0


def test_stock_route_obeys_authentication_settings_date_and_redaction(monkeypatch):
    seen = []

    def inputs(asof, generation, subject=None):
        seen.append(asof)
        raw = observations()
        if subject == "FOSTOCK":
            raw.loc[subject] = raw.loc["C"]
            raw.attrs["comparison_subject"] = subject
        elif subject is not None:
            raw = raw.iloc[:0]
        return raw, DAY

    monkeypatch.setattr(ranker, "_cached_inputs", inputs)
    path = "/ranker/stock/A"
    with TestClient(app) as client:
        assert client.post(path, json={}).status_code == 401
        app.dependency_overrides[auth.get_current_user] = lambda: object()
        try:
            result = client.post(
                path,
                params={"asof": str(DAY)},
                json={"agents": {"momentum": 1}, "factors": {"ret_1m": 1}},
            )
            assert result.status_code == 200
            momentum = next(a for a in result.json()["agents"] if a["agent"] == "momentum")
            assert result.json()["composite"]["score"] == momentum["score"]
            assert seen == [DAY] and "0.17612763" not in result.text
            outsider = client.post(
                "/ranker/stock/fostock", params={"asof": str(DAY)}, json={}
            ).json()
            assert outsider["peer_comparison"] and outsider["in_universe"] is False
            assert (
                len(outsider["agents"]) == 4 and outsider["composite"]["selection"]["side"] is None
            )
            unknown = client.post(
                "/ranker/stock/UNKNOWN", params={"asof": str(DAY)}, json={}
            ).json()
            assert unknown["universe"] == len(observations()) and "agents" not in unknown
            assert client.post(path, json={"mode": "bad"}).status_code == 422
            assert (
                client.post(
                    path, params={"asof": date.today() + timedelta(days=2)}, json={}
                ).status_code
                == 422
            )
        finally:
            app.dependency_overrides.pop(auth.get_current_user)


def test_directory_stock_compares_to_nifty_without_changing_any_member_or_book():
    raw = observations()
    extra = raw.loc[["A"]].rename(index={"A": "FOSTOCK"})
    extra.loc["FOSTOCK", ["ret_1m", "ret_6m", "rsi14", "sector", "pe_ttm"]] = [
        1.3,
        2.2,
        65,
        "Outside sector",
        18,
    ]
    augmented = pd.concat([raw, extra])
    augmented.attrs["comparison_subject"] = "FOSTOCK"
    for mode in ["weighted", "consensus", "hybrid"]:
        cfg = RankSettings(size=1, mode=mode, agree=1)
        reference, books = score_book(raw, cfg)
        trial, trial_books = score_book(augmented, cfg)
        pd.testing.assert_frame_equal(reference, trial.loc[raw.index], check_flags=False)
        assert trial_books == books
        out = stock_analysis(augmented, cfg, DAY, DAY, "FOSTOCK")
        assert (
            out["peer_comparison"] and out["in_universe"] is False and out["universe"] == len(raw)
        )
        assert out["composite"]["selection"]["side"] is None
        momentum = next(a for a in out["agents"] if a["agent"] == "momentum")
        assert momentum["rank"] == 1 and momentum["peers"] == len(raw) + 1
        assert momentum["selection"]["side"] is None
        fund = next(a for a in out["agents"] if a["agent"] == "fundamental")
        pe = next(f for f in fund["factors"] if f["key"] == "pe_ttm")
        assert pe["value"] == 18 and pe["score"] is None and pe["status"] == "no_comparable_peers"


def test_directory_loading_checks_membership_date_and_symbol():
    from stock_agents.engine.ranker_inputs import snapshot_inputs
    from stock_agents.storage.schema import connect, init_schema

    with connect(":memory:") as conn:
        init_schema(conn)
        conn.execute(
            "INSERT INTO symbology(ticker,active) VALUES ('A',TRUE),('FOSTOCK',TRUE),('OLD',FALSE)"
        )
        conn.execute(
            "INSERT INTO index_membership VALUES ('NIFTY500','A',?,NULL,?),('NSE_FO','FOSTOCK',?,NULL,?)",
            [DAY] * 4,
        )
        for t, val in [("A", 0.15), ("FOSTOCK", 0.24)]:
            conn.execute(
                "INSERT INTO fundamentals_pit VALUES (?,'roe_ttm','FY25',?,?,?,'eodhd')",
                [t, val, DAY, DAY],
            )
            conn.execute(
                "INSERT INTO classification(ticker,effective_date,known_date,sector,source) VALUES (?,?,?,'Banks','eodhd')",
                [t, DAY, DAY],
            )
        members, _ = snapshot_inputs(conn, DAY)
        assert members.index.tolist() == ["A"]
        augmented, market = snapshot_inputs(conn, DAY, subject="FOSTOCK")
        out = stock_analysis(augmented, RankSettings(), DAY, market, "FOSTOCK")
        assert out["in_universe"] is False and out["peer_comparison"] is True
        assert out["composite"]["score"] == 75 and out["composite"]["selection"]["side"] is None
        for sym in ["UNKNOWN", "OLD"]:
            assert snapshot_inputs(conn, DAY, subject=sym)[0].empty
        assert snapshot_inputs(conn, DAY - timedelta(days=1), subject="FOSTOCK")[0].empty
