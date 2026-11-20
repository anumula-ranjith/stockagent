"""News tests use an isolated PostgreSQL database; no fixtures enter live storage."""
import csv
import io
import json
from datetime import UTC, date, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from stock_agents.ingest import company_news as ingest
from stock_agents.api import company_news as api
from stock_agents.api.auth import get_current_user


def filing(key="one",symbol="PAYTM",time="2026-11-13 14:42:39"):
    return {"seq_id":key,"symbol":symbol,"sm_name":"One 97 Communications Limited",
            "sort_date":time,"attchmntText":'Paytm approval, "wallet"\nNew line',"attchmntFile":"https://nsearchives.nseindia.in/test.pdf"}


def test_nse_optional_fields_and_time():
    row=filing(); row.pop("attchmntText"); row.pop("attchmntFile")
    parsed=ingest.parse_nse([row],"equities")[0]
    assert parsed["published_at"]==datetime(2026,11,13,9,12,39,tzinfo=UTC)
    assert parsed["source_key"]=="one" and parsed["url"].startswith("https://www.nseindia.in/")
    with pytest.raises(ValueError): ingest.parse_nse([{"symbol":"PAYTM"}],"sme")


def test_matching_and_symbols():
    companies=[{"symbol":s,"aliases":ingest.company_aliases(s,n)} for s,n in
               [("PAYTM","One 97 Communications Limited"),("INFY","Infosys Limited"),("IDEA","Vodafone Idea Limited")]]
    assert ingest.normalize_symbol(" paytm.ns ")=="PAYTM"
    for name in ("Paytm","One 97 Communications","One97 Communications"):
        assert ingest.matching_companies(name+" results",companies)==["PAYTM"]
    assert ingest.matching_companies("Paytm and Infosys results",companies)==["PAYTM","INFY"]
    assert ingest.matching_companies("new IDEA for payment companies",companies)==[]
    assert ingest.matching_companies("Paytmology",companies)==[]


def test_ist_boundaries():
    lo,hi=ingest.boundaries(date(2026,11,13),None)
    assert lo==datetime(2026,11,12,18,30,tzinfo=UTC)
    assert hi==datetime(2026,11,13,18,30,tzinfo=UTC)
    assert (lo,hi)==ingest.boundaries(None,date(2026,11,13))
    assert (ingest.boundaries(date(2026,11,13),date(2026,11,14))[1]-lo).days==2
    with pytest.raises(ValueError): ingest.boundaries(date(2026,11,14),date(2026,11,13))


def test_rss_and_domain_validation():
    payload=b'''<rss><channel><item><title>Paytm earnings</title><link>https://news.google.com/rss/articles/test</link>
      <source url="https://www.moneycontrol.com">Moneycontrol</source><pubDate>Fri, 13 Nov 2026 10:00:00 GMT</pubDate></item>
      <item><title>Invalid</title><link>https://evil.example/a</link><pubDate>Fri, 13 Nov 2026 10:00:00 GMT</pubDate></item></channel></rss>'''
    rows,rejected=ingest.parse_rss(payload,"Moneycontrol")
    assert len(rows)==1 and rejected==1 and rows[0]["source"]=="Moneycontrol"
    assert ingest.parse_rss(payload,"Moneycontrol")[0][0]["source_key"]==rows[0]["source_key"]
    with pytest.raises(ValueError): ingest.parse_rss(b'<!DOCTYPE rss><rss/>',"Mint")
    assert ingest.parse_rss(b'<rss><channel><item><title>missing</title></item></channel></rss>',"Mint")[1]==1


@pytest.fixture
def news_db(auth_database,monkeypatch):
    monkeypatch.setattr(api,"sync_engine",lambda:auth_database)
    with auth_database.begin() as conn:
        for symbol,name in [("PAYTM","One 97 Communications Limited"),("INFY","Infosys Limited")]:
            conn.execute(text("INSERT INTO news_companies(symbol,name,segment,aliases) VALUES (:s,:n,'equities',CAST(:a AS jsonb))"),
                dict(s=symbol,n=name,a=json.dumps(ingest.company_aliases(symbol,name))))
    return auth_database


def test_transactional_dedup_pagination_csv_and_coverage(news_db):
    rows=ingest.parse_nse([filing(str(i)) for i in range(105)],"equities")
    rows[0]["symbols"]=["PAYTM","INFY"]
    rows[1]["title"]="=HYPERLINK(\"unsafe\")"
    with news_db.begin() as conn:
        ingest.store_items(conn,rows); ingest.store_items(conn,rows)
        ingest.record_coverage(conn,"NSE equities",date(2026,11,13),"success",105)
        assert conn.execute(text("SELECT count(*) FROM news_items")).scalar()==105
        assert conn.execute(text("SELECT count(*) FROM news_item_companies")).scalar()==106
    app=FastAPI();app.include_router(api.router)
    with TestClient(app) as client:
        assert client.get("/company-news").status_code==401
        assert client.get("/company-news/export.csv").status_code==401
        app.dependency_overrides[get_current_user]=lambda:{"id":"test"}
        params=dict(symbol="PAYTM.NS",start="2026-11-13",kind="announcement")
        pages=[client.get("/company-news",params={**params,"page":p}).json() for p in (1,2,3)]
        assert [len(p["items"]) for p in pages]==[50,50,5]
        assert pages[0]["total"]==105
        assert len({r["id"] for p in pages for r in p["items"]})==105
        export=client.get("/company-news/export.csv",params=params)
        assert export.content.startswith(b'\xef\xbb\xbf')
        exported=list(csv.DictReader(io.StringIO(export.content.decode("utf-8-sig"))))
        assert len(exported)==105
        assert [r["Title"] for r in exported]==[api.csv_safe(r["title"]) for p in pages for r in p["items"]]
        assert any(r["Symbols"]=="INFY; PAYTM" for r in exported)
        assert any(r["Title"].startswith("'=") for r in exported)
        assert any('\n' in r["Title"] for r in exported)
        assert client.get("/company-news",params={**params,"symbol":"Paytm"}).json()["total"]==105
        assert client.get("/company-news",params={**params,"symbol":"One 97 Communications"}).json()["total"]==105
        assert client.get("/company-news",params={"start":"2026-11-14","end":"2026-11-13"}).status_code==422
        assert client.get("/company-news",params={"source":"unknown"}).status_code==422
        missing=client.get("/company-news",params={"start":"2020-01-01"}).json()
        assert missing["total"]==0 and all(c["missing_days"]==1 for c in missing["coverage"])
        with news_db.begin() as conn: ingest.record_coverage(conn,"NSE equities",date(2026,11,13),"failed",detail="timeout")
        state=client.get("/company-news",params=params).json()["coverage"][0]
        assert state["status"]=="unavailable" and state["last_success"] is not None


def test_one_failed_source_does_not_block_others(news_db,monkeypatch):
    class Response:
        def __init__(self,segment): self.segment=segment
        def json(self): return [filing(self.segment)]
    def fake_get(url,params):
        if params["index"]=="equities": raise ValueError("source unavailable")
        return Response(params["index"])
    monkeypatch.setattr(ingest,"get",fake_get)
    results=ingest.ingest(date(2026,11,13),date(2026,11,13),"nse",news_db)
    assert [r["status"] for r in results]==["failed","success"]
    with news_db.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM news_items")).scalar()==1


def test_scheduled_collection_recovers_gaps_per_source(news_db, monkeypatch):
    class EmptyFeed:
        def json(self):
            return []

    monkeypatch.setattr(ingest, "get", lambda *args: EmptyFeed())
    start, end = date(2025, 1, 1), date(2025, 1, 7)
    with news_db.begin() as conn:
        for day in ingest.days_between(start, end):
            for source in ("NSE equities", "NSE sme"):
                if source == "NSE sme" and day.day == 2:
                    continue
                status = "failed" if source == "NSE equities" and day.day == 3 else "success"
                ingest.record_coverage(conn, source, day, status, 0)
        conn.execute(text("""UPDATE company_news_coverage SET checked_at='2025-01-04 23:59:00+05:30'
                             WHERE source='NSE equities' AND day='2025-01-04'"""))

    def collected_days():
        results = ingest.ingest(start, end, "nse", news_db, scheduled=True)
        assert all(row["status"] == "success" for row in results)
        return {source: [date.fromisoformat(row["day"]).day for row in results if row["source"] == source]
                for source in ("NSE equities", "NSE sme")}

    assert collected_days() == {"NSE equities": [7, 6, 4, 3], "NSE sme": [7, 6, 2]}
    assert collected_days() == {"NSE equities": [7, 6], "NSE sme": [7, 6]}


@pytest.mark.parametrize("value",["=1+1"," +cmd","-1","@SUM(1)","\t=1","\r=1","\n=1"])
def test_csv_formula_safety(value):
    assert api.csv_safe(value).startswith("'")


def test_network_retry_is_bounded(monkeypatch):
    calls=[]
    class Response:
        content=b"[]"
        headers={"Retry-After":"1"}
        def __init__(self,status): self.status_code=status
        def raise_for_status(self):
            if self.status_code>=400: raise ingest.requests.HTTPError(response=self)
    def request(*args,**kwargs):
        calls.append(kwargs["timeout"])
        return Response(429 if len(calls)<3 else 200)
    monkeypatch.setattr(ingest.requests,"get",request)
    monkeypatch.setattr(ingest.time,"sleep",lambda _:None)
    assert ingest.get("https://example.test").status_code==200
    assert len(calls)==3 and calls[0]==(8,25)


def test_associations_rollback_with_article(news_db):
    rows=ingest.parse_nse([filing()],"equities")
    rows[0]["symbols"].append("DOES_NOT_EXIST")
    with pytest.raises(Exception):
        with news_db.begin() as conn:
            ingest.store_items(conn,rows)
    with news_db.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM news_items")).scalar()==0


def test_query_excludes_next_ist_day(news_db):
    rows=ingest.parse_nse([filing("first",time="2026-11-13 00:00:00"),
                           filing("last",time="2026-11-13 23:59:59"),
                           filing("next",time="2026-11-14 00:00:00")],"equities")
    with news_db.begin() as conn: ingest.store_items(conn,rows)
    filters=api.Filters(symbol="",kind="all",source="",start=date(2026,11,13),end=None)
    result=api.list_news(None,filters,page=1,page_size=50)
    assert result["total"]==2 and [r["source_key"] for r in result["items"]]==["last","first"]


def test_latest_seven_exact_stock_preserves_archive(news_db):
    rows=ingest.parse_nse([filing(str(i),time=f"2020-01-{i+1:02d} 10:00:00") for i in range(10)],"equities")
    rows+=ingest.parse_nse([filing("other",symbol="INFY",time="2026-11-20 10:00:00")],"equities")
    with news_db.begin() as conn:
        ingest.store_items(conn,rows)
    app=FastAPI();app.include_router(api.router)
    with TestClient(app) as client:
        assert client.get("/company-news/latest?symbol=PAYTM").status_code==401
        app.dependency_overrides[get_current_user]=lambda:{"id":"test"}
        result=client.get("/company-news/latest?symbol=PAYTM.NS").json()
        assert len(result)==7
        assert [r["source_key"] for r in result]==[str(i) for i in range(9,2,-1)]
        assert client.get("/company-news/latest?symbol=UNKNOWN").json()==[]
        archive=client.get("/company-news",params=dict(symbol="PAYTM",start="2020-01-01",end="2020-01-10")).json()
        assert archive["total"]==10
