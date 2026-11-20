"""Validate every stored free headline score and export an auditable CSV dump."""
import csv
import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text

from stock_agents.api.company_news import csv_safe
from stock_agents.ingest.free_sentiment import MODEL, probabilities, title_hash
from stock_agents.jobs.queue import sync_engine


def main():
    folder=Path('docs/verification')
    folder.mkdir(parents=True,exist_ok=True)
    with sync_engine().connect().execution_options(isolation_level='REPEATABLE READ') as c:
        rows=c.execute(text("""SELECT n.id,n.source,n.title,n.url,n.published_at,s.*,
          (SELECT string_agg(symbol,', ' ORDER BY symbol) FROM news_item_companies nc WHERE nc.news_item_id=n.id) symbols
          FROM news_items n LEFT JOIN company_news_sentiment s ON s.news_item_id=n.id
          WHERE n.kind='headline' ORDER BY n.published_at DESC,n.id DESC""")).mappings().all()
        issues=[]
        for r in rows:
            try:
                probabilities([{'label':k,'score':r[k]} for k in ('positive','negative','neutral')])
                assert r['model']==MODEL and r['title_hash']==title_hash(r['title'])
                assert abs(r['polarity']-(r['positive']-r['negative']))<1e-8
                assert r['symbols'] and r['url'].startswith(('https://','http://'))
                assert r['published_at']<=datetime.now(UTC) and r['scored_at']>=r['published_at']
            except (TypeError,ValueError,AssertionError): issues.append(r['id'])
        summary={
          'checked_at':datetime.now(UTC).isoformat(),'model':MODEL,'headlines_checked':len(rows),
          'invalid_or_unscored_ids':issues,
          'by_publisher':[dict(r) for r in c.execute(text("SELECT n.source,count(*) headlines FROM news_items n JOIN company_news_sentiment s ON s.news_item_id=n.id GROUP BY n.source")).mappings()],
          'daily_aggregates':dict(c.execute(text("SELECT count(*) stock_days,count(distinct ticker) stocks FROM sentiment_daily WHERE source='free_news_finbert'")).mappings().one()),
          'universe_without_scored_headlines':c.scalar(text("""SELECT count(*) FROM symbology sy WHERE sy.active
            AND EXISTS(SELECT 1 FROM index_membership m WHERE m.ticker=sy.ticker AND m.index_code IN ('NIFTY500','NSE_FO')
              AND m.joined_on<=CURRENT_DATE AND m.known_on<=CURRENT_DATE AND (m.left_on IS NULL OR m.left_on>CURRENT_DATE))
            AND NOT EXISTS(SELECT 1 FROM sentiment_daily d WHERE d.ticker=sy.ticker AND d.source='free_news_finbert')""")),
          'duplicate_source_keys':c.scalar(text("SELECT count(*) FROM (SELECT source,source_key FROM news_items GROUP BY source,source_key HAVING count(*)>1) d")),
          'news_pipeline_runs':[dict(r) for r in c.execute(text("SELECT id,status,created_at FROM pipeline_runs WHERE dedupe_key LIKE 'free-sentiment-cutover%' ORDER BY created_at DESC")).mappings()],
        }
    with (folder/'free-news-sentiment.csv').open('w',newline='',encoding='utf-8-sig') as file:
        writer=csv.writer(file)
        fields=['id','symbols','source','title','url','published_at','positive','negative','neutral','polarity','model','scored_at']
        writer.writerow(fields)
        for r in rows: writer.writerow([csv_safe(r[k]) for k in fields])
    (folder/'free-news-sentiment-audit.json').write_text(json.dumps(summary,indent=2,default=str),encoding='utf-8')
    print(json.dumps(summary,default=str))
    if issues or summary['duplicate_source_keys']: raise SystemExit(1)


if __name__=='__main__': main()
