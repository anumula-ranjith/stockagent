from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import select, text

from stock_agents.sources.eodhd import EODHDClient


def test_client_stops_account_errors_and_honors_retry_after(monkeypatch):
    import pytest
    from stock_agents.sources import eodhd
    waits=[]
    monkeypatch.setattr(eodhd.time,'sleep',waits.append)
    replies=iter([SimpleNamespace(status_code=429,headers={'Retry-After':'2'}),
                  SimpleNamespace(status_code=402,headers={})])
    monkeypatch.setattr(eodhd.requests,'get',lambda *a,**k:next(replies))
    with pytest.raises(eodhd.EODHDAccountError) as error:
        EODHDClient('secret').news('INFY.NSE')
    assert error.value.status_code==402 and waits==[2]


def test_morning_evening_slots_and_cancelled_quota_wait(auth_database,monkeypatch):
    from stock_agents.ingest.eodhd_news import refresh_slot
    from stock_agents.jobs import pipelines,pipeline_stages
    from stock_agents.jobs.pipeline_models import PipelineRun
    assert refresh_slot(datetime(2026,11,19,1,30,tzinfo=UTC))=='2026-11-19-morning'
    assert refresh_slot(datetime(2026,11,19,13,tzinfo=UTC))=='2026-11-19-evening'
    for key in ('morning','evening'):
        run=pipelines.submit('daily',pipelines.latest_session(),'verification:'+key)
        calls=[]
        monkeypatch.setattr(pipeline_stages,'run_stage',lambda name,day:calls.append(name) or {'status':'ok'})
        pipelines.execute(run['id'])
        assert tuple(calls)==pipelines.PIPELINES['daily']
        with auth_database.connect() as c:
            assert c.scalar(select(PipelineRun.status).where(PipelineRun.id==run['id']))=='success'
    run=pipelines.submit('news',pipelines.latest_session(),'cancel-quota')
    def pending(name,day):
        if name=='news':
            pipelines.set_run(run['id'],cancel_requested=True)
            return {'status':'awaiting_quota','retry_at':(datetime.now(UTC)+timedelta(hours=1)).isoformat()}
        return {'status':'ok'}
    monkeypatch.setattr(pipeline_stages,'run_stage',pending)
    pipelines.execute(run['id'])
    with auth_database.connect() as c:
        row=c.execute(select(PipelineRun.__table__).where(PipelineRun.id==run['id'])).mappings().one()
        assert row['status']=='cancelled' and row['next_attempt_at'] is None


def test_account_budget_handles_lazy_reset_and_extra_units(monkeypatch):
    monkeypatch.setattr(EODHDClient, '_get', lambda *args: {
        'apiRequests': 100000, 'dailyRateLimit': 100000, 'extraLimit': 10,
        'apiRequestsDate': str((datetime.now(UTC)-timedelta(days=1)).date())})
    assert EODHDClient('secret').remaining_calls() == 100010


def test_quota_wait_resume_and_other_schedule_can_run(auth_database, monkeypatch):
    from stock_agents.jobs import pipelines, pipeline_stages
    from stock_agents.jobs.pipeline_models import PipelineRun
    run = pipelines.submit('news', pipelines.latest_session(), 'quota-test')
    calls=[]
    def stage(name, day):
        calls.append(name)
        return {'status':'awaiting_quota','retry_at':(datetime.now(UTC)+timedelta(hours=2)).isoformat(),
                'reason':'EODHD quota exhausted'} if name=='news' else {'status':'ok'}
    monkeypatch.setattr(pipeline_stages,'run_stage',stage)
    pipelines.execute(run['id'])
    with auth_database.connect() as conn:
        row=conn.execute(select(PipelineRun.__table__)).mappings().one()
        assert row['status']=='retrying' and row['next_attempt_at'] and not row['finished_at']
    other=pipelines.submit('validate',pipelines.latest_session(),'other-schedule')
    pipelines.execute(other['id'])
    monkeypatch.setattr(pipeline_stages,'run_stage',lambda *args:{'status':'ok'})
    pipelines.set_run(run['id'],next_attempt_at=None)
    pipelines.execute(run['id'])
    with auth_database.connect() as conn:
        assert conn.scalar(select(PipelineRun.status).where(PipelineRun.id==run['id']))=='success'


def test_checkpoint_reuses_completed_members_and_waits_without_calls(auth_database, monkeypatch):
    from stock_agents.ingest.eodhd_news import refresh_eodhd_news
    client=SimpleNamespace(remaining_calls=lambda: 4)
    with auth_database.begin() as conn:
        conn.execute(text("INSERT INTO symbology(ticker,eodhd_symbol,active) VALUES ('INFY','INFY.NSE',true)"))
        conn.execute(text("INSERT INTO index_membership(index_code,ticker,joined_on,known_on) VALUES ('NIFTY500','INFY','2020-01-01','2020-01-01')"))
        result=refresh_eodhd_news(conn,'news',client=client)
        assert result['status']=='awaiting_quota' and result['pending']==1
        calls=[]
        client.remaining_calls=lambda:1000
        client.news=lambda *args,**kwargs:calls.append(args[0]) or []
        assert refresh_eodhd_news(conn,'news',client=client)['status']=='ok'
        assert refresh_eodhd_news(conn,'news',client=client)['reused']==1
        assert calls==['INFY.NSE']
