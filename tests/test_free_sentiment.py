from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from stock_agents.ingest.free_sentiment import probabilities, refresh_sentiment


def test_technical_prices_choose_one_vendor_per_day(auth_database):
    from datetime import date
    from stock_agents.storage.warehouse import Warehouse
    from stock_agents.factors.technical import _prices_pivot
    with auth_database.begin() as c:
        c.execute(text("INSERT INTO symbology(ticker) VALUES ('TESTPRICE')"))
        c.execute(text("""INSERT INTO prices_daily(ticker,date,adj_close,source,known_date)
          VALUES ('TESTPRICE','2026-11-19',100,'eodhd','2026-11-19'),
                 ('TESTPRICE','2026-11-19',101,'nse_bhavcopy','2026-11-19')"""))
        pivot=_prices_pivot(Warehouse(c),date(2026,11,19))
        assert len(pivot)==1 and pivot.iloc[0]['TESTPRICE']==100


def test_probabilities_validate_model_output():
    result=probabilities([{"label":"positive","score":0.8},{"label":"negative","score":0.1},{"label":"neutral","score":0.1}])
    assert result["polarity"]==pytest.approx(0.7)
    with pytest.raises(ValueError): probabilities([{"label":"positive","score":float("nan")}])
    with pytest.raises(ValueError): probabilities([{"label":"positive","score":1.0}])
    from stock_agents.api.company_news import csv_safe
    assert csv_safe(0)=="0"


def test_atomic_idempotent_sentiment_and_history(auth_database):
    engine=auth_database
    with engine.begin() as c:
        c.execute(text("INSERT INTO symbology(ticker) VALUES ('PAYTM')"))
        c.execute(text("INSERT INTO news_companies(symbol,name,segment,aliases) VALUES ('PAYTM','One97','equities','[]')"))
        for key in ('a','b'):
            nid=c.execute(text("INSERT INTO news_items(kind,source,source_key,title,url,published_at) VALUES ('headline','Mint',:k,'Paytm profit rises','https://example.com/'||:k,'2026-11-19 23:00:00+05:30') RETURNING id"),{'k':key}).scalar_one()
            c.execute(text("INSERT INTO news_item_companies VALUES (:id,'PAYTM')"),{'id':nid})
    calls=[]
    def predict(titles):
        calls.extend(titles)
        return [[{'label':'positive','score':0.8},{'label':'negative','score':0.1},{'label':'neutral','score':0.1}] for _ in titles]
    when=datetime(2026,11,20,6,tzinfo=UTC)
    with engine.begin() as c: first=refresh_sentiment(c,predict=predict,now=when)
    with engine.begin() as c: second=refresh_sentiment(c,predict=predict,now=when)
    assert first['scored']==2 and second['scored']==0 and len(calls)==1
    with engine.connect() as c:
        row=c.execute(text("SELECT * FROM sentiment_daily WHERE source='free_news_finbert'")).mappings().one()
        assert row['n_headlines']==1  # repeated publisher/title does not inflate signals
        assert str(row['effective_date'])=='2026-11-19'
        assert str(row['known_date'])=='2026-11-20'  # no backdated knowledge
        assert row['polarity']==pytest.approx(0.7)
        assert c.execute(text('SELECT count(*) FROM news_items')).scalar()==2
    with engine.begin() as c:
        c.execute(text("UPDATE news_items SET title='Changed headline' WHERE source_key='a'"))
    with pytest.raises(ValueError):
        with engine.begin() as c: refresh_sentiment(c,predict=lambda titles: [],now=when)
