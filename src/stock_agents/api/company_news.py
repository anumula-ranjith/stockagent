"""Authenticated company news list, directory lookup and streamed CSV."""
import csv
import io
import re
from datetime import date, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import text

from stock_agents.api.auth import CurrentUser
from stock_agents.ingest.company_news import IST, SOURCES, boundaries, normalize_symbol
from stock_agents.jobs.queue import sync_engine

router = APIRouter(prefix="/company-news", tags=["company-news"])


class Filters:
    def __init__(self, symbol: str = Query("", max_length=160),
                 kind: Literal["all", "headline", "announcement"] = "all",
                 source: str = Query("", max_length=80), start: date | None = None, end: date | None = None):
        if source and source not in SOURCES:
            raise HTTPException(422, "Unknown publisher or exchange")
        try:
            self.lo, self.hi = boundaries(start, end)
        except (ValueError, OverflowError) as exc:
            raise HTTPException(422, str(exc)) from None
        self.symbol, self.kind, self.source = symbol.strip(), kind, source
        self.start = self.lo.astimezone(IST).date()
        self.end = self.hi.astimezone(IST).date()-timedelta(days=1)
        if (self.end-self.start).days > 366:
            raise HTTPException(422, "Select at most 367 days")

    def sql(self):
        terms = ["n.published_at>=:lo", "n.published_at<:hi"]
        params = dict(lo=self.lo, hi=self.hi)
        if self.kind != "all":
            terms.append("n.kind=:kind"); params["kind"] = self.kind
        if self.source:
            terms.append("n.source=:source"); params["source"] = self.source
        if self.symbol:
            terms.append("""EXISTS(SELECT 1 FROM news_item_companies nc JOIN news_companies c USING(symbol)
              WHERE nc.news_item_id=n.id AND (c.symbol=:symbol OR position(:term in lower(c.name))>0
              OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(c.aliases) a WHERE position(:term in a)>0)))""")
            params.update(symbol=normalize_symbol(self.symbol),term=self.symbol.casefold())
        return " AND ".join(terms), params


Selected = Annotated[Filters, Depends()]
ROW_SQL = """SELECT n.*, (SELECT jsonb_build_object('polarity',s.polarity,'positive',s.positive,
  'negative',s.negative,'neutral',s.neutral,'model',s.model,'scored_at',s.scored_at,
  'label',CASE WHEN s.neutral>=greatest(s.positive,s.negative) THEN 'Neutral'
    WHEN s.positive>=s.negative THEN 'Positive' ELSE 'Negative' END)
  FROM company_news_sentiment s WHERE s.news_item_id=n.id) AS sentiment, (SELECT jsonb_agg(jsonb_build_object('symbol',c.symbol,'name',c.name) ORDER BY c.symbol)
  FROM news_item_companies nc JOIN news_companies c USING(symbol) WHERE nc.news_item_id=n.id) AS companies
  FROM news_items n WHERE {where} ORDER BY n.published_at DESC,n.id DESC"""


def coverage(conn, filters):
    expected = [s for s in SOURCES if (not filters.source or s == filters.source)
                and (filters.kind == "all" or s.startswith("NSE ") == (filters.kind == "announcement"))]
    rows = conn.execute(text("SELECT * FROM company_news_coverage WHERE day BETWEEN :start AND :end"),
                        dict(start=filters.start,end=filters.end)).mappings().all()
    result=[]
    for source in expected:
        records=[dict(r) for r in rows if r["source"] == source]
        missing=(filters.end-filters.start).days+1-len(records)
        latest=max((r["checked_at"] for r in records),default=None)
        success=conn.execute(text("SELECT max(last_success) FROM company_news_coverage WHERE source=:s"),dict(s=source)).scalar()
        failed=sum(r["status"] in ("failed","partial") for r in records)
        result.append(dict(source=source,missing_days=missing,failed_days=failed,
            status="unavailable" if failed else "not_collected" if missing else "limited" if not source.startswith("NSE ") else "collected",
            last_success=success,checked_at=latest,details=records))
    return result


@router.get("")
def list_news(user: CurrentUser, filters: Selected, page: int = Query(1,ge=1,le=1000000), page_size: int = Query(50,ge=1,le=100)):
    where, params=filters.sql()
    # One consistent snapshot for totals, records and source state.
    with sync_engine().connect().execution_options(isolation_level="REPEATABLE READ") as conn:
        total=conn.execute(text("SELECT count(*) FROM news_items n WHERE "+where),params).scalar_one()
        rows=conn.execute(text(ROW_SQL.format(where=where)+" LIMIT :limit OFFSET :offset"),
            {**params,"limit":page_size,"offset":(page-1)*page_size}).mappings().all()
        return dict(items=[dict(r) for r in rows],total=total,page=page,page_size=page_size,
                    start=filters.start,end=filters.end,coverage=coverage(conn,filters))


@router.get("/companies")
def companies(user: CurrentUser, q: str = Query("",max_length=160)):
    with sync_engine().connect() as conn:
        return [dict(r) for r in conn.execute(text("""SELECT symbol,name,segment FROM news_companies
          WHERE :q='' OR symbol=:symbol OR position(:term in lower(name))>0
          OR position(:term in lower(symbol))>0
          OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(aliases) a WHERE position(:term in a)>0)
          ORDER BY (symbol=:symbol) DESC,symbol LIMIT 20"""),dict(q=q,symbol=normalize_symbol(q),term=q.strip().casefold())).mappings()]


def csv_safe(value):
    value=str("" if value is None else value)
    return "'"+value if value.lstrip().startswith(("=","+","-","@","\t","\r")) or value.startswith(("\t","\r","\n")) else value


def csv_chunks(filters, engine=None):
    where,params=filters.sql()
    output=io.StringIO(newline="")
    writer=csv.writer(output)
    yield "\ufeff"
    writer.writerow(["Type","Published (IST)","Symbols","Companies","Source","Title","URL","Sentiment estimate","Sentiment model"])
    yield output.getvalue(); output.seek(0); output.truncate(0)
    with (engine or sync_engine()).connect().execution_options(stream_results=True,yield_per=500) as conn:
        rows=conn.execute(text(ROW_SQL.format(where=where)),params).mappings()
        for row in rows:
            fields=[row["kind"],row["published_at"].astimezone(IST).strftime("%Y-%m-%d %H:%M:%S %z"),
                "; ".join(c["symbol"] for c in row["companies"]),"; ".join(c["name"] for c in row["companies"]),
                row["source"],row["title"],row["url"],
                row['sentiment']['polarity'] if row['sentiment'] else '',
                row['sentiment']['model'] if row['sentiment'] else '']
            writer.writerow([csv_safe(v) for v in fields])
            yield output.getvalue(); output.seek(0); output.truncate(0)


@router.get("/export.csv")
def export_news(user: CurrentUser, filters: Selected):
    scope=re.sub(r"[^A-Za-z0-9_-]", "_", filters.symbol)[:80] or "all-NSE"
    filename=f"news-{scope}-{filters.start}-{filters.end}.csv"
    return StreamingResponse(csv_chunks(filters),media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition":f'attachment; filename="{filename}"',"Cache-Control":"no-store"})


@router.get("/latest")
def latest_news(user: CurrentUser, symbol: str = Query(..., min_length=1, max_length=160)):
    """Seven newest stored stories for one exact stock, without a date cutoff."""
    where = "EXISTS(SELECT 1 FROM news_item_companies nc WHERE nc.news_item_id=n.id AND nc.symbol=:symbol)"
    with sync_engine().connect() as conn:
        rows = conn.execute(text(ROW_SQL.format(where=where)+" LIMIT 7"),
                            {"symbol": normalize_symbol(symbol)}).mappings().all()
        return [dict(row) for row in rows]
