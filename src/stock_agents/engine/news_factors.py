"""Observed news attention and a coverage-gated historical comparison."""
import numpy as np
import pandas as pd
from datetime import timedelta


def baseline_complete(conn, asof):
    covered=conn.execute("""SELECT count(*) FROM company_news_coverage
      WHERE day BETWEEN ? AND ? AND checked_at < ((CAST(? AS date) + INTERVAL '1 day') AT TIME ZONE 'Asia/Kolkata')
      AND source IN ('Mint','The Economic Times','Moneycontrol','Business Standard')
      AND status IN ('success','limited')""",[asof-timedelta(days=29),asof,asof]).fetchone()[0]
    return covered==120


def news_factors(news, asof, *, baseline_available):
    news=news.copy()
    news['age']=news['day'].map(lambda d:(asof-d).days)
    recent=news.loc[news.age.between(0,6)].copy()
    mass=recent['count']*2.0**(-recent.age/2)
    result=pd.DataFrame(index=pd.Index(news.ticker.unique(),name='ticker'))
    result['news_tone_7d']=(recent.tone*mass).groupby(recent.ticker).sum(min_count=1)/mass.where(recent.tone.notna()).groupby(recent.ticker).sum(min_count=1)
    result['headlines']=recent.groupby('ticker')['count'].sum()
    result['news_attention_7d']=result['headlines']
    result['news_volume']=np.nan
    if baseline_available:
        normal=news.loc[news.age.between(3,29)].groupby('ticker')['count'].sum()/27
        current=news.loc[news.age.between(0,2)].groupby('ticker')['count'].sum().reindex(normal.index,fill_value=0)/3
        result['news_volume']=current/normal.where(normal>0)
    return result
