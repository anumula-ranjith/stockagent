import asyncio
from datetime import date, timedelta

from stock_agents.api import personal


def test_quotes_bind_calendar_dates_and_deduplicate_sources(monkeypatch):
    asof = date(2026, 11, 19)
    monkeypatch.setattr(personal, "today", lambda: asof)
    monkeypatch.setattr(personal, "_quote_cache", {})

    class Session:
        calls = []

        async def execute(self, statement, parameters):
            self.calls.append((str(statement), parameters))
            assert "CURRENT_DATE" not in str(statement)
            assert parameters["asof"] == asof
            assert parameters["cutoff"] == asof - timedelta(days=14)
            return self

        def all(self):
            return [("INFY", asof, 110), ("INFY", asof, 109),
                    ("INFY", asof - timedelta(days=1), 100)]

    session = Session()
    result = asyncio.run(personal.quotes(session, ["INFY"]))
    assert result["INFY"].close == 110
    assert round(result["INFY"].change_pct, 6) == 10
    asyncio.run(personal.quotes(session, ["INFY"]))
    assert len(session.calls) == 1


def test_quotes_fall_back_for_old_listing(monkeypatch):
    asof = date(2026, 11, 19)
    monkeypatch.setattr(personal, "today", lambda: asof)
    monkeypatch.setattr(personal, "_quote_cache", {})

    class Session:
        calls = 0

        async def execute(self, statement, parameters):
            self.calls += 1
            if self.calls == 2:
                assert "date < :cutoff" in str(statement)
            return self

        def all(self):
            return [("OLD", None, None)] if self.calls == 1 else [
                ("OLD", asof - timedelta(days=30), 20),
                ("OLD", asof - timedelta(days=31), 25)]

    result = asyncio.run(personal.quotes(Session(), ["OLD"]))
    assert result["OLD"].close == 20
    assert round(result["OLD"].change_pct, 6) == -20
