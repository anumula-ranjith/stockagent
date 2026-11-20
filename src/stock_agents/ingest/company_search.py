"""Rotating company-specific discovery supplements publisher-wide RSS feeds."""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from datetime import datetime, timedelta

from sqlalchemy import text

from stock_agents.ingest.company_news import (
    IST, PUBLISHERS, company_aliases, get, matching_companies, parse_rss, record_coverage, safe_error, store_items,
)
from stock_agents.jobs.queue import sync_engine


def parse_search(payload, companies):
    records={}
    for publisher in PUBLISHERS:
        rows,_=parse_rss(payload,publisher)
        for row in rows:
            row['symbols']=matching_companies(row['title'],companies)
            if row['symbols']: records[(row['source'],row['source_key'])]=row
    return list(records.values())


def refresh_company_search(limit=25):
    if not 1<=limit<=600: raise ValueError('Company batch must be between 1 and 600')
    engine=sync_engine();now=datetime.now(IST)
    results=[]
    with engine.connect() as lock:
        if not lock.scalar(text('SELECT pg_try_advisory_lock(490122895)')):
            return {'status':'already_running','companies':0}
        lock.commit()
        try:
            # NSE equity CSVs omit some index-listed REITs. Use only verified NSE
            # reference identities to make those investable members searchable.
            with engine.begin() as c:
                missing=c.execute(text("""SELECT cr.ticker,cr.company_name,cr.isin FROM company_reference cr
                  JOIN symbology sy USING(ticker) LEFT JOIN news_companies nc ON nc.symbol=cr.ticker
                  WHERE nc.symbol IS NULL AND sy.active AND cr.source='nse_indices'""")).mappings().all()
                for row in missing:
                    c.execute(text("""INSERT INTO news_companies(symbol,name,segment,isin,instrument_ticker,aliases)
                      VALUES (:ticker,:company_name,'nse_index_member',:isin,:ticker,CAST(:aliases AS jsonb))
                      ON CONFLICT(symbol) DO NOTHING"""),{**dict(row),'aliases':json.dumps(company_aliases(row['ticker'],row['company_name']))})
            with engine.connect() as c:
                directory=[dict(r) for r in c.execute(text('SELECT symbol,name,aliases FROM news_companies')).mappings()]
                batch=c.execute(text("""SELECT nc.symbol,nc.name,nc.aliases FROM news_companies nc
                  JOIN symbology sy ON sy.ticker=nc.symbol
                  LEFT JOIN LATERAL (SELECT max(checked_at) checked FROM company_news_coverage
                    WHERE source='Company search '||nc.symbol) last ON true
                  WHERE sy.active AND EXISTS(SELECT 1 FROM index_membership m WHERE m.ticker=sy.ticker
                    AND m.index_code IN ('NIFTY500','NSE_FO') AND m.joined_on<=:today AND m.known_on<=:today
                    AND (m.left_on IS NULL OR m.left_on>:today))
                  ORDER BY last.checked ASC NULLS FIRST,nc.symbol LIMIT :limit"""),{'today':now.date(),'limit':limit}).mappings().all()
            pace=Lock()
            next_request=[0.0]
            def fetch(company):
                source='Company search '+company['symbol']
                try:
                    aliases=company['aliases'][:3] or [company['name']]
                    names=' OR '.join('"'+a.replace('"','')+'"' for a in aliases)
                    sites=' OR '.join('site:'+v[0] for v in PUBLISHERS.values())
                    with pace:
                        delay=max(0,next_request[0]-time.monotonic())
                        if delay: time.sleep(delay)
                        next_request[0]=time.monotonic()+1.0
                    payload=get('https://news.google.com/rss/search',{'q':f'({names}) ({sites}) when:7d','hl':'en-IN','gl':'IN','ceid':'IN:en'}).content
                    items=[r for r in parse_search(payload,directory) if now-timedelta(days=7)<=r['published_at']<=now]
                    with engine.begin() as c:
                        store_items(c,items)
                        record_coverage(c,source,now.date(),'limited',len(items),'Company-specific seven-day search; search indexing is not exhaustive.')
                    return {'symbol':company['symbol'],'status':'limited','items':len(items)}
                except Exception as exc:
                    with engine.begin() as c: record_coverage(c,source,now.date(),'failed',detail=safe_error(exc))
                    return {'symbol':company['symbol'],'status':'failed'}
            with ThreadPoolExecutor(max_workers=3) as pool:
                results=list(pool.map(fetch,batch))
        finally:
            lock.execute(text('SELECT pg_advisory_unlock(490122895)'));lock.commit()
    return {'status':'partial' if any(r['status']=='failed' for r in results) else 'ok','companies':len(results),'results':results}


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--limit',type=int,default=25)
    print(json.dumps(refresh_company_search(parser.parse_args().limit)))
