"""Compare sentiment-input coverage after source expansion; no data mutations."""
import json
from datetime import datetime
from pathlib import Path
from sqlalchemy import text
from stock_agents.ingest.company_news import IST
from stock_agents.storage.warehouse import connect
from stock_agents.engine.ranker_inputs import snapshot_inputs
from stock_agents.jobs.queue import sync_engine

now=datetime.now(IST)
with connect(read_only=True) as conn:
    frame,price_day=snapshot_inputs(conn,now.date())
keys=['news_tone_7d','news_attention_7d','news_volume','insider_activity','nse_short_selling_activity','short_interest','social_buzz']
for key in keys:
    if key not in frame: frame[key]=float('nan')
report={'checked_at':now.isoformat(),'stocks':len(frame),'price_date':str(price_day),'coverage':{key:int(frame[key].notna().sum()) for key in keys}}
with sync_engine().connect() as c:
    report['company_search']=dict(c.execute(text("SELECT count(*) companies,count(*) FILTER(WHERE status='failed') failed,sum(item_count) matches FROM company_news_coverage WHERE source LIKE 'Company search %'")).mappings().one())
    report['headlines']=dict(c.execute(text("SELECT count(*) stored,count(s.news_item_id) scored FROM news_items n LEFT JOIN company_news_sentiment s ON s.news_item_id=n.id WHERE n.kind='headline'")).mappings().one())
folder=Path('docs/verification')
frame[keys].to_csv(folder/'news-expansion-stock-coverage.csv',encoding='utf-8-sig',index_label='ticker')
(folder/'news-expansion-audit.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report))
