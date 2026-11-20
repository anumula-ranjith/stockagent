from stock_agents.ingest.company_search import parse_search


def test_index_reit_missing_from_equity_directory_is_searched(auth_database, monkeypatch):
    from sqlalchemy import text
    from stock_agents.ingest import company_search
    with auth_database.begin() as c:
        c.execute(text("INSERT INTO symbology(ticker) VALUES ('BIRET')"))
        c.execute(text("""INSERT INTO company_reference(ticker,company_name,venue,source,observed_on)
          VALUES ('BIRET','Brookfield India Real Estate Trust','NSE','nse_indices',CURRENT_DATE)"""))
        c.execute(text("""INSERT INTO index_membership(ticker,index_code,joined_on,known_on)
          VALUES ('BIRET','NIFTY500',CURRENT_DATE,CURRENT_DATE)"""))
    monkeypatch.setattr(company_search,'sync_engine',lambda:auth_database)
    monkeypatch.setattr(company_search,'get',lambda *a,**kw:type('Response',(),{'content':b'<rss><channel/></rss>'})())
    monkeypatch.setattr(company_search.time,'sleep',lambda _:None)
    result=company_search.refresh_company_search(limit=1)
    assert result['companies']==1 and result['results'][0]['symbol']=='BIRET'
    with auth_database.connect() as c:
        assert c.scalar(text("SELECT name FROM news_companies WHERE symbol='BIRET'"))=='Brookfield India Real Estate Trust'


def test_baseline_requires_all_publishers_days_and_known_collection(auth_database):
    from sqlalchemy import text
    from datetime import date
    from stock_agents.storage.warehouse import Warehouse
    from stock_agents.engine.news_factors import baseline_complete
    with auth_database.begin() as c:
        c.execute(text("""INSERT INTO company_news_coverage(source,day,status,checked_at)
          SELECT source,d::date,'limited','2026-11-20 12:00:00+05:30'
          FROM unnest(ARRAY['Mint','The Economic Times','Moneycontrol','Business Standard']) source
          CROSS JOIN generate_series('2026-10-22'::date,'2026-11-20'::date,'1 day') d"""))
        assert baseline_complete(Warehouse(c),date(2026,11,20))
        assert not baseline_complete(Warehouse(c),date(2026,11,19))
        c.execute(text("UPDATE company_news_coverage SET status='failed' WHERE source='Mint' AND day='2026-11-19'"))
        assert not baseline_complete(Warehouse(c),date(2026,11,20))


def test_news_attention_and_volume_require_baseline():
    import pandas as pd
    from datetime import date
    from stock_agents.engine.news_factors import news_factors
    rows=pd.DataFrame([['A',date(2026,11,19),0.5,3],['A',date(2026,11,10),0.1,9],
                       ['B',date(2026,11,10),0.1,9]],columns=['ticker','day','tone','count'])
    result=news_factors(rows,date(2026,11,20),baseline_available=True)
    assert result.loc['A','news_attention_7d']==3
    assert result.loc['A','news_volume']==3
    assert result.loc['B','news_volume']==0
    assert news_factors(rows,date(2026,11,20),baseline_available=False)['news_volume'].isna().all()


def test_company_search_rejects_unrelated_and_unknown_publishers():
    companies=[{'symbol':'PAYTM','aliases':['paytm']},{'symbol':'INFY','aliases':['infosys']}]
    payload=b'''<rss><channel>
      <item><title>Paytm profit rises</title><link>https://news.google.com/rss/articles/a</link><source url="https://www.moneycontrol.com">Moneycontrol</source><pubDate>Fri, 20 Nov 2026 10:00:00 GMT</pubDate></item>
      <item><title>Unrelated update</title><link>https://www.livemint.com/b</link><pubDate>Fri, 20 Nov 2026 10:00:00 GMT</pubDate></item>
      <item><title>Paytm profit</title><link>https://evil.example/b</link><pubDate>Fri, 20 Nov 2026 10:00:00 GMT</pubDate></item>
    </channel></rss>'''
    rows=parse_search(payload,companies)
    assert len(rows)==1 and rows[0]['symbols']==['PAYTM'] and rows[0]['source']=='Moneycontrol'
