"""Local FinBERT headline estimates from the independent free company news feed.

No article bodies are fetched. Exchange announcement boilerplate is excluded.
Raw stories and old vendor observations are retained for audit, never deleted.
"""
import hashlib
import math
import re
from datetime import UTC, datetime
from functools import lru_cache

from sqlalchemy import text

from stock_agents.ingest.company_news import IST

REVISION = "0bc2ac10dda6929bcb1f77ccc43c7ec5c424f031"
MODEL = "ProsusAI/finbert@"+REVISION
SOURCE = "free_news_finbert"


def clean_title(value):
    return re.sub(r"\s+", " ", value).strip()


def title_hash(value):
    return hashlib.sha256(clean_title(value).casefold().encode()).hexdigest()


def probabilities(scores):
    values={r['label'].lower():float(r['score']) for r in scores}
    if len(scores)!=3 or set(values)!={'positive','negative','neutral'} or any(not math.isfinite(x) or not 0<=x<=1 for x in values.values()) or abs(sum(values.values())-1)>0.001:
        raise ValueError('Invalid financial sentiment probabilities')
    return {**values,'polarity':values['positive']-values['negative']}


@lru_cache(maxsize=1)
def classifier():
    import torch
    from transformers import AutoTokenizer, AutoModelForSequenceClassification, pipeline
    torch.set_num_threads(2)
    tokenizer=AutoTokenizer.from_pretrained('ProsusAI/finbert',revision=REVISION,trust_remote_code=False)
    model=AutoModelForSequenceClassification.from_pretrained('ProsusAI/finbert',revision=REVISION,trust_remote_code=False)
    return pipeline('text-classification',model=model,tokenizer=tokenizer,device=-1)


def predict_titles(titles):
    return classifier()(titles,top_k=None,batch_size=16,truncation=True,max_length=512)


def refresh_sentiment(conn, *, predict=None, now=None):
    """Caller owns transaction. Fail atomically; never convert an error to neutral."""
    now=now or datetime.now(UTC)
    # Daily and 15-minute jobs may meet here. Wait for the small transaction
    # rather than reporting a healthy overlapping update as partial.
    previous_timeout=conn.scalar(text("SHOW lock_timeout"))
    conn.execute(text("SELECT set_config('lock_timeout','60s',true)"))
    conn.execute(text('SELECT pg_advisory_xact_lock(490122894)'))
    conn.execute(text("SELECT set_config('lock_timeout',:value,true)"),{'value':previous_timeout})
    rows=conn.execute(text("""SELECT n.id,n.title,s.title_hash,s.model FROM news_items n
      LEFT JOIN company_news_sentiment s ON s.news_item_id=n.id
      WHERE n.kind='headline' AND n.published_at<=:now AND btrim(n.title)<>''
      AND n.source IN ('Mint','The Economic Times','Moneycontrol','Business Standard')
      ORDER BY n.id"""),{'now':now}).mappings().all()
    pending=[r for r in rows if r['model']!=MODEL or r['title_hash']!=title_hash(r['title'])]
    unique={title_hash(r['title']):clean_title(r['title']) for r in pending}
    scores={}
    keys=list(unique)
    for offset in range(0,len(keys),32):
        batch=keys[offset:offset+32]
        results=(predict or predict_titles)([unique[k] for k in batch])
        if len(results)!=len(batch): raise ValueError('Sentiment model returned an incomplete batch')
        scores.update({key:probabilities(value) for key,value in zip(batch,results)})
    for r in pending:
        key=title_hash(r['title'])
        conn.execute(text("""INSERT INTO company_news_sentiment
          (news_item_id,model,title_hash,scored_at,positive,negative,neutral,polarity)
          VALUES (:id,:model,:hash,:now,:positive,:negative,:neutral,:polarity)
          ON CONFLICT(news_item_id) DO UPDATE SET model=EXCLUDED.model,title_hash=EXCLUDED.title_hash,
          scored_at=EXCLUDED.scored_at,positive=EXCLUDED.positive,negative=EXCLUDED.negative,
          neutral=EXCLUDED.neutral,polarity=EXCLUDED.polarity"""),
          dict(id=r['id'],model=MODEL,hash=key,now=now,**scores[key]))
    # Collapse repeated headlines per company/IST day before counting. Known date
    # records when the model output actually became available, not publication day.
    conn.execute(text("""INSERT INTO sentiment_daily(ticker,effective_date,polarity,n_headlines,source,known_date)
      SELECT ticker,day,avg(polarity),count(*),:source,max(known) FROM (
        SELECT nc.symbol AS ticker,(n.published_at AT TIME ZONE 'Asia/Kolkata')::date AS day,
          s.title_hash,avg(s.polarity) AS polarity,
          max((s.scored_at AT TIME ZONE 'Asia/Kolkata')::date) AS known
        FROM news_items n JOIN company_news_sentiment s ON s.news_item_id=n.id
        JOIN news_item_companies nc ON nc.news_item_id=n.id JOIN symbology sy ON sy.ticker=nc.symbol
        WHERE s.model=:model AND n.kind='headline' AND n.published_at<=:now
        GROUP BY nc.symbol,day,s.title_hash
      ) observations GROUP BY ticker,day
      ON CONFLICT(ticker,effective_date,source) DO UPDATE SET polarity=EXCLUDED.polarity,
      n_headlines=EXCLUDED.n_headlines,known_date=EXCLUDED.known_date
      WHERE (sentiment_daily.polarity,sentiment_daily.n_headlines,sentiment_daily.known_date)
        IS DISTINCT FROM (EXCLUDED.polarity,EXCLUDED.n_headlines,EXCLUDED.known_date)"""),
      {'source':SOURCE,'model':MODEL,'now':now})
    counts=conn.execute(text("SELECT count(*) days,count(distinct ticker) stocks FROM sentiment_daily WHERE source=:s"),{'s':SOURCE}).mappings().one()
    return dict(status='ok',model=MODEL,eligible=len(rows),scored=len(pending),**dict(counts))


if __name__=='__main__':
    import json
    from stock_agents.jobs.queue import sync_engine
    with sync_engine().begin() as connection:
        result=refresh_sentiment(connection)
    print(json.dumps(result))
