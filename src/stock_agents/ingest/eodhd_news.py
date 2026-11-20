"""Quota-aware, resumable EODHD news/sentiment refresh for both daily slots."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, time, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from stock_agents.ingest.news import ingest_news, ingest_sentiment_daily
from stock_agents.sources.eodhd import EODHDAccountError, EODHDClient
from stock_agents.storage.postgres import Base
from stock_agents.storage.warehouse import Warehouse


def refresh_slot(now):
    local = now.astimezone(ZoneInfo("Asia/Kolkata"))
    if local.time() < time(7):
        return f"{local.date()-timedelta(days=1)}-evening"
    return f"{local.date()}-" + ("evening" if local.time() >= time(18,30) else "morning")


def refresh_eodhd_news(conn, kind, *, client=None):
    if kind not in ("news", "sentiment"):
        raise ValueError("Unsupported news endpoint")
    now = datetime.now(UTC)
    day = now.astimezone(ZoneInfo("Asia/Kolkata")).date()
    run_id = f"eodhd-{kind}-{refresh_slot(now)}"
    saved = conn.scalar(text("SELECT warnings FROM run_log WHERE run_id=:id"), {"id":run_id})
    state = json.loads(saved) if saved else {"complete":[],"rows":0}
    members = conn.execute(text("""SELECT s.ticker,s.eodhd_symbol FROM symbology s
        WHERE s.active AND EXISTS (SELECT 1 FROM index_membership m WHERE m.ticker=s.ticker
        AND m.index_code IN ('NIFTY500','NSE_FO') AND m.joined_on<=:day AND m.known_on<=:day
        AND (m.left_on IS NULL OR m.left_on>:day)) ORDER BY s.ticker"""), {"day":day}).all()
    if not members:
        raise RuntimeError("EODHD news universe is empty")
    done = set(state["complete"])
    pending = [(t,s) for t,s in members if s and f"{t}:{s}" not in done]
    reused = len(members)-len(pending)-sum(not s for _,s in members)
    state.update(status="ok", members=len(members), errors={}, reused=reused, retry_at=None, reason=None)
    state["missing_symbols"] = [t for t,s in members if not s]
    client = client or EODHDClient.from_env()
    reset = (now+timedelta(days=1)).replace(hour=0,minute=5,second=0,microsecond=0)

    def quota_wait():
        state.update(status="awaiting_quota", reason="EODHD daily quota exhausted; resumes after reset",
                     retry_at=reset.isoformat())

    def fetch(member):
        ticker,symbol = member
        try:
            return member, client.news(symbol,limit=50), None
        except Exception as exc:
            return member, None, exc

    for offset in range(0,len(pending),20 if kind=="news" else 50):
        batch = pending[offset:offset+(20 if kind=="news" else 50)]
        # Conservative units: news <=10/ticker, sentiment <=5+5/ticker.
        cost = 10*len(batch) if kind=="news" else 5+5*len(batch)
        try:
            remaining = client.remaining_calls()
            state["remaining_units"] = remaining
            if remaining < cost:
                quota_wait()
                break
            if kind=="news":
                with ThreadPoolExecutor(max_workers=4) as pool:
                    results = list(pool.map(fetch,batch))
                for (ticker,symbol),items,error in results:
                    if error:
                        if isinstance(error,EODHDAccountError) and error.status_code==402:
                            quota_wait()
                        else:
                            state["errors"][ticker] = type(error).__name__
                        continue
                    # Parse/store only this response; no second provider request.
                    replay = SimpleNamespace(news=lambda *a, payload=items, **kw: payload)
                    with conn.begin_nested():
                        result = ingest_news(Warehouse(conn),replay,tickers=[ticker],report=True)
                    if result["status"]=="ok":
                        done.add(f"{ticker}:{symbol}")
                        state["rows"] += result["rows"]
                    else:
                        state["errors"][ticker] = "Invalid news data"
                if state["status"]=="awaiting_quota":
                    break
                # Invalid credentials affect all remaining symbols; don't hammer the account.
                if any(isinstance(error,EODHDAccountError) for _,_,error in results):
                    break
            else:
                with conn.begin_nested():
                    result = ingest_sentiment_daily(Warehouse(conn),client,tickers=[t for t,_ in batch],report=True)
                if result["status"]=="ok":
                    done.update(f"{t}:{s}" for t,s in batch)
                    state["rows"] += result["rows"]
                else:
                    state["errors"]["batch"] = "Sentiment response incomplete"
        except EODHDAccountError as exc:
            if exc.status_code==402:
                quota_wait()
            else:
                state["errors"]["account"] = f"EODHD HTTP {exc.status_code}"
            break
        except Exception as exc:
            state["errors"]["batch"] = type(exc).__name__
            break
    state["complete"] = sorted(done)
    state["pending"] = sum(f"{t}:{s}" not in done for t,s in members)
    if state["status"] != "awaiting_quota" and (state["pending"] or state["errors"]):
        state["status"] = "partial"
    log = Base.metadata.tables["run_log"]
    stmt = insert(log).values(run_id=run_id,job=f"eodhd_{kind}",started_at=now.replace(tzinfo=None),
        ended_at=datetime.now(UTC).replace(tzinfo=None),status=state["status"],rows_written=state["rows"],warnings=json.dumps(state))
    conn.execute(stmt.on_conflict_do_update(index_elements=[log.c.run_id],set_={
        "ended_at":stmt.excluded.ended_at,"status":stmt.excluded.status,"rows_written":stmt.excluded.rows_written,"warnings":stmt.excluded.warnings}))
    return {k:v for k,v in state.items() if k!="complete"}
