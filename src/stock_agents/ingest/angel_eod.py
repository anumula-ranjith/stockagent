"""Recover completed-session OHLCV from official Angel One daily candles."""
import json
import math
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from stock_agents.jobs.pipelines import TZ, latest_session
from stock_agents.sources.angel_market import fetch_daily_candles
from stock_agents.sources.angel_one import AngelOneError
from stock_agents.sources.nse import NSEClient
from stock_agents.storage.postgres import Base


def refresh_angel_eod(conn, day):
    if day > latest_session():
        raise ValueError("Only completed sessions can be recovered")
    log = Base.metadata.tables["run_log"]
    run_id = f"angel-eod-{day}"
    previous = conn.scalar(select(log.c.warnings).where(log.c.run_id==run_id,log.c.status=="ok"))
    if previous:
        return {**json.loads(previous),"reused":True}
    members = list(conn.scalars(text("""SELECT DISTINCT s.ticker FROM symbology s JOIN index_membership m USING(ticker)
        WHERE s.active AND m.index_code IN ('NIFTY500','NSE_FO') AND m.joined_on<=:day AND m.known_on<=:known
        AND (m.left_on IS NULL OR m.left_on>:day) ORDER BY s.ticker"""),{"day":day,"known":datetime.now(TZ).date()}))
    if not members:
        raise RuntimeError("No members available for Angel One recovery")
    prices=Base.metadata.tables["prices_daily"]
    written=0
    recovered=set()
    known=datetime.now(TZ).date()
    fallback = set()
    def candles():
        try:
            yield from ((ticker,candle,"angel_one") for ticker,candle in fetch_daily_candles(members,day))
        except AngelOneError:
            pass  # The final exchange file below must still validate complete coverage.
        missing = set(members)-recovered
        if missing:
            client = NSEClient()
            try:
                book = client.bhavcopy(day)
            finally:
                client.close()
            for ticker in sorted(missing):
                row = book.get(ticker)
                if row:
                    fallback.add(ticker)
                    yield ticker,[str(day),row["open"],row["high"],row["low"],row["close"],row["volume"]],"nse_bhavcopy"
    for ticker,candle,source in candles():
        try:
            opening,high,low,close=map(float,candle[1:5])
            volume=int(candle[5])
        except (ValueError,TypeError,OverflowError):
            continue
        if not all(math.isfinite(v) and v>0 for v in (opening,high,low,close)) or not low<=min(opening,close)<=max(opening,close)<=high or volume<=0:
            continue
        # Retain a previously verified adjustment only when its raw close agrees.
        adjusted=conn.scalar(select(prices.c.adj_close).where(prices.c.ticker==ticker,prices.c.date==day,
            prices.c.source.in_(("eodhd","nse_bhavcopy")),prices.c.adj_close>0,
            prices.c.close.between(close-0.011,close+0.011)).order_by((prices.c.source=="eodhd").desc()).limit(1))
        stmt=insert(prices).values(ticker=ticker,date=day,known_date=known,source=source,open=opening,high=high,low=low,
            close=close,volume=volume,adj_close=adjusted,exchange_trade_at=None)
        written+=conn.execute(stmt.on_conflict_do_update(index_elements=list(prices.primary_key.columns),
            set_={c.name:stmt.excluded[c.name] for c in prices.columns if not c.primary_key})).rowcount
        recovered.add(ticker)
    missing=sorted(set(members)-recovered)
    result={"status":"partial" if missing else "ok","trade_date":str(day),"members":len(members),"priced":len(recovered),
        "written":written,"missing":missing,"method":"Completed-session candles with verified NSE fallback",
        "angel_one_bars":len(recovered-fallback),"nse_fallback_bars":len(recovered&fallback),
        "fallback_reason":"Angel One daily candle unavailable" if fallback else None,"live_capture_reconstructed":False}
    record=insert(log).values(run_id=run_id,job="angel_eod",started_at=datetime.now(UTC).replace(tzinfo=None),
        ended_at=datetime.now(UTC).replace(tzinfo=None),status=result["status"],rows_written=written,warnings=json.dumps(result))
    conn.execute(record.on_conflict_do_update(index_elements=[log.c.run_id],set_={
        "status":record.excluded.status,"ended_at":record.excluded.ended_at,"rows_written":written,"warnings":record.excluded.warnings}))
    return result
