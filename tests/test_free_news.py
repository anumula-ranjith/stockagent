from datetime import UTC, datetime

import pytest

from stock_agents.ingest.free_news import aliases, matches, parse_feed


def test_matching_requires_company_or_unambiguous_symbol():
    assert matches('Infosys wins contract', aliases('INFY', 'Infosys Limited'))
    assert matches('ITC shares rise', aliases('ITC', 'ITC Limited'))
    assert not matches('A new idea for investment', aliases('IDEA', 'Vodafone Idea Limited'))
    assert matches('Vodafone Idea raises capital', aliases('IDEA', 'Vodafone Idea Limited'))
    assert not matches('Tata Motors rises', aliases('TATAPOWER', 'Tata Power Company Limited'))
    assert matches('Tata Power wins contract', aliases('TATAPOWER', 'Tata Power Company Limited'))
    assert matches('SBI reports profit', aliases('SBIN', 'State Bank of India'))
    assert not matches('SBI Life reports profit', aliases('SBIN', 'State Bank of India'))
    assert matches('L&T wins orders', aliases('LT', 'Larsen & Toubro Ltd.'))
    assert not matches('L&T Finance reports profit', aliases('LT', 'Larsen & Toubro Ltd.'))
    assert matches('Adani Ports grows', aliases('ADANIPORTS', 'Adani Ports and Special Economic Zone Ltd.'))
    assert matches('LIC reports profit', aliases('LICI', 'Life Insurance Corporation of India'))
    assert not matches('LIC Housing Finance reports profit', aliases('LICI', 'Life Insurance Corporation of India'))


def test_feed_sanitizes_dates_links_and_duplicates():
    xml = b'''<rss><channel><item><title>Infosys &amp; growth</title><link>https://economictimes.indiatimes.com/a?utm_source=rss</link><pubDate>Thu, 19 Nov 2026 10:00:00 GMT</pubDate></item><item><title>Unsafe</title><link>javascript:alert(1)</link><pubDate>Thu, 19 Nov 2026 10:00:00 GMT</pubDate></item><item><title>Bad date</title><link>https://example.org/a</link><pubDate>bad</pubDate></item></channel></rss>'''
    items, rejected = parse_feed(xml, datetime(2026, 11, 19, 12, tzinfo=UTC))
    assert len(items) == 1 and rejected == 2
    assert items[0]['headline'] == 'Infosys & growth'
    assert items[0]['url'] == 'https://economictimes.indiatimes.com/a'
    assert items[0]['polarity'] is None


def test_feed_rejects_html_and_entities():
    for body in (b'<html>blocked</html>', b'<!DOCTYPE rss [<!ENTITY x "abc">]><rss><channel/></rss>'):
        with pytest.raises(ValueError):
            parse_feed(body, datetime.now(UTC))


def test_union_persistence_deduplication_and_feed_failure(auth_database, monkeypatch):
    from sqlalchemy import text
    from stock_agents.ingest import free_news
    item = dict(headline='INFY and TCS report earnings', url='https://economictimes.indiatimes.com/a',
                published_at=datetime.now(UTC), source=free_news.SOURCE, polarity=None)
    monkeypatch.setattr(free_news, 'fetch_feed', lambda *args: ([item], 0))
    with auth_database.begin() as conn:
        conn.execute(text("INSERT INTO symbology(ticker,active) VALUES ('INFY',true),('TCS',true),('OTHER',true)"))
        conn.execute(text("""INSERT INTO index_membership(index_code,ticker,joined_on,known_on) VALUES
            ('NIFTY500','INFY','2020-01-01','2020-01-01'),('NSE_FO','INFY','2020-01-01','2020-01-01'),
            ('NSE_FO','TCS','2020-01-01','2020-01-01')"""))
        first = free_news.ingest_free_news(conn)
        second = free_news.ingest_free_news(conn)
        assert first['members'] == 2 and first['rows'] == 2 and first['articles'] == 1
        assert second['rows'] == 0 and second['duplicates'] == 2
        assert conn.scalar(text('select count(*) from news where polarity is null')) == 2
        def failure(*args):
            raise ValueError('bad feed')
        monkeypatch.setattr(free_news, 'fetch_feed', failure)
        failed = free_news.ingest_free_news(conn)
        assert failed['status'] == 'failed' and failed['feeds_ok'] == 0
        assert conn.scalar(text('select count(*) from news')) == 2


def test_news_stage_runs_free_source_without_paid_key(monkeypatch):
    from contextlib import contextmanager
    from stock_agents.jobs import pipeline_stages
    from stock_agents.ingest import free_news
    class Settings:
        def env(self, key):
            return None
    @contextmanager
    def writer():
        yield object()
    monkeypatch.setattr(pipeline_stages, 'load_settings', lambda: Settings())
    monkeypatch.setattr(pipeline_stages, 'warehouse_writer', writer)
    monkeypatch.setattr(free_news, 'ingest_free_news', lambda _: {'status': 'ok', 'members': 501})
    assert pipeline_stages.run_stage('news', datetime.now().date())['members'] == 501
    monkeypatch.setattr(free_news, 'ingest_free_news', lambda _: {'status': 'failed'})
    assert pipeline_stages.run_stage('news', datetime.now().date())['status'] == 'partial'


def test_paid_failure_does_not_rollback_free_import(auth_database, monkeypatch):
    from sqlalchemy import text
    from stock_agents.ingest import free_news, eodhd_news
    from stock_agents.jobs import pipeline_stages
    from stock_agents.sources.eodhd import EODHDClient
    class Settings:
        def env(self, key):
            return 'configured'
    monkeypatch.setattr(pipeline_stages, 'load_settings', lambda: Settings())
    monkeypatch.setattr(pipeline_stages, 'warehouse_writer', auth_database.begin)
    monkeypatch.setattr(EODHDClient, 'from_env', lambda: object())
    def broken(*args, **kwargs):
        raise AttributeError('malformed paid payload')
    monkeypatch.setattr(eodhd_news, 'refresh_eodhd_news', broken)
    item = dict(headline='INFY wins contract', url='https://economictimes.indiatimes.com/a',
                published_at=datetime.now(UTC), source=free_news.SOURCE, polarity=None)
    monkeypatch.setattr(free_news, 'fetch_feed', lambda *args: ([item], 0))
    with auth_database.begin() as conn:
        conn.execute(text("INSERT INTO symbology(ticker,active) VALUES ('INFY',true)"))
        conn.execute(text("INSERT INTO index_membership(index_code,ticker,joined_on,known_on) VALUES ('NIFTY500','INFY','2020-01-01','2020-01-01')"))
    result = pipeline_stages.run_stage('news', datetime.now().date())
    assert result['status'] == 'partial' and result['eodhd']['status'] == 'failed'
    with auth_database.connect() as conn:
        assert conn.scalar(text('select count(*) from news')) == 1
        assert conn.scalar(text("select count(*) from run_log where job='free_news'")) == 1


def test_api_collapses_tracking_url_duplicates():
    import asyncio
    from stock_agents.api.main import news
    class DB:
        async def fetch(self, *args, **kwargs):
            ts=datetime.now(UTC)
            return [(ts,'Infosys news','Paid','https://economictimes.indiatimes.com/a',0.2,None,None,None),
                    (ts,'Infosys news','RSS','https://economictimes.indiatimes.com/a?utm_source=rss',None,None,None,None)]
    result=asyncio.run(news('INFY', DB(), limit=15))
    assert len(result)==1 and result[0]['polarity']==0.2
