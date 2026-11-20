"""Independent NSE company news. Run with --directory or --start YYYY-MM-DD."""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime, time as daytime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from zoneinfo import ZoneInfo

import requests
from sqlalchemy import text
from stock_agents.jobs.queue import sync_engine

IST = ZoneInfo("Asia/Kolkata")
PUBLISHERS = {
    "Mint": ("livemint.com", "https://www.livemint.com/rss/companies"),
    "The Economic Times": ("economictimes.indiatimes.com", "https://economictimes.indiatimes.com/markets/stocks/news/rssfeeds/2146842.cms"),
    "Moneycontrol": ("moneycontrol.com", None),  # Direct RSS is stale (August 2024).
    "Business Standard": ("business-standard.com", "https://www.business-standard.com/rss/markets-106.rss"),
}
SOURCES = ["NSE equities", "NSE sme", *PUBLISHERS]
BRANDS = {"PAYTM": ["Paytm", "One 97 Communications", "One97 Communications"],
          "ETERNAL": ["Zomato", "Blinkit"], "INFY": ["Infosys"],
          "SBIN": ["State Bank of India"], "TCS": ["Tata Consultancy Services"],
          "BHARTIARTL": ["Bharti Airtel"], "RELIANCE": ["Reliance Industries"],
          "M&M": ["Mahindra and Mahindra"], "LT": ["Larsen and Toubro"],
          "DMART": ["Avenue Supermarts", "DMart"]}
DIRECTORIES = {"equities": "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
               "sme": "https://nsearchives.nseindia.com/emerge/corporates/content/SME_EQUITY_L.csv"}


def normalized(value):
    return re.sub(r"[^a-z0-9]+", " ", value.casefold().replace("&", " and ")).strip()


def normalize_symbol(value):
    return re.sub(r"\.(?:NS|NSE)$", "", value.strip().upper())


def boundaries(start: date | None, end: date | None):
    if start is None and end is None:
        end = datetime.now(IST).date()
        start = end - timedelta(days=6)
    start, end = start or end, end or start
    if start > end:
        raise ValueError("Start date must not be after end date")
    return (datetime.combine(start, daytime.min, IST).astimezone(UTC),
            datetime.combine(end + timedelta(days=1), daytime.min, IST).astimezone(UTC))


def days_between(start, end):
    if start > end:
        raise ValueError("Start date must not be after end date")
    for offset in range((end-start).days+1):
        yield start + timedelta(days=offset)


def get(url, params=None):
    """Three bounded attempts; respect long Retry-After by ending this poll."""
    for attempt in range(3):
        try:
            response = requests.get(url, params=params, timeout=(8, 25), headers={
                "User-Agent": "Mozilla/5.0", "Accept": "application/json,application/xml,text/xml,*/*"})
            if response.status_code == 429 or response.status_code >= 500:
                retry = response.headers.get("Retry-After", "2")
                try:
                    delay = int(retry) if retry.isdigit() else max(0, int((parsedate_to_datetime(retry)-datetime.now(UTC)).total_seconds())+1)
                except (TypeError, ValueError, OverflowError):
                    delay = 2
                if delay > 30:
                    response.raise_for_status()
                if attempt < 2:
                    time.sleep(max(delay, 2**attempt)); continue
            response.raise_for_status()
            if len(response.content) > 25_000_000:
                raise ValueError("Source response exceeds safe size")
            return response
        except (requests.Timeout, requests.ConnectionError):
            if attempt == 2:
                raise
            time.sleep(2**attempt)
    raise RuntimeError("Source request failed")


def company_aliases(symbol, name):
    clean = re.sub(r"\s+(?:limited|ltd\.?)$", "", name, flags=re.I).strip()
    values = [clean, *BRANDS.get(symbol, [])]
    # No automatic ticker matching: short English words are unsafe.
    return sorted({normalized(v) for v in values if len(normalized(v)) >= 4})


def matching_companies(title, companies):
    value = " " + normalized(title) + " "
    return [c["symbol"] for c in companies if any(" " + a + " " in value for a in c["aliases"])]


def record_coverage(conn, source, day, status, count=0, detail=""):
    conn.execute(text("""INSERT INTO company_news_coverage(source,day,status,item_count,detail,last_success)
      VALUES (:s,:d,:status,:n,:detail,CASE WHEN :status IN ('success','limited') THEN now() END)
      ON CONFLICT(source,day) DO UPDATE SET status=EXCLUDED.status,checked_at=now(),
      item_count=EXCLUDED.item_count,detail=EXCLUDED.detail,
      last_success=COALESCE(EXCLUDED.last_success,company_news_coverage.last_success)"""),
      dict(s=source,d=day,status=status,n=count,detail=detail))


def safe_error(exc):
    if isinstance(exc, requests.HTTPError):
        return "Source HTTP " + str(exc.response.status_code)
    return (str(exc) if isinstance(exc, ValueError) else type(exc).__name__)[:250]


def refresh_directory(engine=None):
    engine = engine or sync_engine()
    results = {}
    for segment, url in DIRECTORIES.items():
        try:
            payload = get(url).content.decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(payload))
            rows = [{k.strip().replace("_", " "): (v or "").strip() for k,v in r.items() if k} for r in reader]
            if not rows or not {"SYMBOL","NAME OF COMPANY"}.issubset(rows[0]):
                raise ValueError("Unexpected NSE directory schema")
            with engine.begin() as conn:
                for row in rows:
                    symbol, name = row["SYMBOL"], row["NAME OF COMPANY"]
                    if not symbol or not name:
                        raise ValueError("Missing company identity")
                    conn.execute(text("""INSERT INTO news_companies(symbol,name,segment,isin,instrument_ticker,aliases)
                      VALUES (:symbol,:name,:segment,:isin,(SELECT ticker FROM symbology WHERE ticker=:symbol),CAST(:aliases AS jsonb))
                      ON CONFLICT(symbol) DO UPDATE SET name=EXCLUDED.name,segment=EXCLUDED.segment,
                      isin=EXCLUDED.isin,instrument_ticker=EXCLUDED.instrument_ticker,aliases=EXCLUDED.aliases,updated_at=now()"""),
                      dict(symbol=symbol,name=name,segment=segment,isin=row.get("ISIN NUMBER"),aliases=json.dumps(company_aliases(symbol,name))))
                record_coverage(conn,"Directory "+segment,datetime.now(IST).date(),"success",len(rows))
            results[segment] = len(rows)
        except Exception as exc:
            with engine.begin() as conn:
                record_coverage(conn,"Directory "+segment,datetime.now(IST).date(),"failed",detail=safe_error(exc))
            results[segment] = {"error":safe_error(exc)}
    return results


def safe_url(value, fallback=None):
    parsed = urlsplit(value or "")
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        if fallback:
            return fallback
        raise ValueError("Invalid source link")
    return value


def parse_nse(payload, segment):
    if not isinstance(payload, list):
        raise ValueError("Expected NSE announcements array")
    records = []
    for r in payload:
        if not r.get("seq_id") or not r.get("symbol"):
            raise ValueError("NSE filing missing stable ID or symbol")
        stamp = r.get("sort_date") or r.get("an_dt")
        try:
            published = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            published = datetime.strptime(stamp, "%d-%b-%Y %H:%M:%S")
        title = (r.get("attchmntText") or r.get("desc") or "NSE corporate announcement").strip()
        records.append(dict(kind="announcement",source="NSE "+segment,source_key=str(r["seq_id"]),
            title=html.unescape(title),url=safe_url(r.get("attchmntFile"),"https://www.nseindia.in/companies-listing/corporate-filings-announcements"),
            published_at=published.replace(tzinfo=IST).astimezone(UTC),symbols=[r["symbol"].strip().upper()],
            company_name=r.get("sm_name") or r["symbol"],isin=r.get("sm_isin"),segment=segment))
    return records


def domain_matches(url, domain):
    host = (urlsplit(url).hostname or "").lower()
    return host == domain or host.endswith("."+domain)


def parse_rss(payload, publisher):
    if len(payload)>5_000_000 or b"<!ENTITY" in payload.upper() or b"<!DOCTYPE" in payload.upper():
        raise ValueError("Unsafe or oversized RSS document")
    root = ET.fromstring(payload)
    if root.tag != "rss" or root.find("channel") is None:
        raise ValueError("Expected RSS channel")
    domain = PUBLISHERS[publisher][0]
    records, rejected = [], 0
    for item in root.findall("./channel/item"):
        try:
            title = html.unescape(item.findtext("title") or "").strip()
            url = safe_url((item.findtext("link") or "").strip())
            published = parsedate_to_datetime(item.findtext("pubDate") or "")
            if not title or published.tzinfo is None:
                raise ValueError("Missing headline or timestamp")
            if domain_matches(url,"news.google.com"):
                source = item.find("source")
                if source is None or not domain_matches(source.get("url", ""), domain):
                    raise ValueError("Google result publisher domain mismatch")
            elif not domain_matches(url, domain):
                raise ValueError("Publisher domain mismatch")
            parts = urlsplit(url)
            url = urlunsplit((parts.scheme, parts.netloc, parts.path,
                urlencode([(k,v) for k,v in parse_qsl(parts.query) if not k.lower().startswith("utm_")]), ""))
            key = hashlib.sha256(url.encode()).hexdigest()
            records.append(dict(kind="headline",source=publisher,source_key=key,title=title,url=url,published_at=published.astimezone(UTC)))
        except (ValueError, TypeError, OverflowError):
            rejected += 1
    return records, rejected


def store_items(conn, items):
    for item in items:
        if not item.get("symbols"):
            continue
        if item["kind"] == "announcement":
            symbol = item["symbols"][0]
            conn.execute(text("""INSERT INTO news_companies(symbol,name,segment,isin,aliases,instrument_ticker)
              VALUES (:symbol,:name,:segment,:isin,CAST(:aliases AS jsonb),(SELECT ticker FROM symbology WHERE ticker=:symbol))
              ON CONFLICT(symbol) DO NOTHING"""),dict(symbol=symbol,name=item["company_name"],segment=item["segment"],
                isin=item.get("isin"),aliases=json.dumps(company_aliases(symbol,item["company_name"]))))
        news_id = conn.execute(text("""INSERT INTO news_items(kind,source,source_key,title,url,published_at)
          VALUES (:kind,:source,:source_key,:title,:url,:published_at)
          ON CONFLICT(source,source_key) DO UPDATE SET title=EXCLUDED.title,url=EXCLUDED.url
          RETURNING id"""),item).scalar_one()
        for symbol in set(item["symbols"]):
            conn.execute(text("INSERT INTO news_item_companies VALUES (:id,:symbol) ON CONFLICT DO NOTHING"),dict(id=news_id,symbol=symbol))


def google_feed(publisher, day):
    domain = PUBLISHERS[publisher][0]
    query = f"site:{domain} (shares OR stock OR earnings OR results) after:{day-timedelta(days=1)} before:{day+timedelta(days=2)}"
    return get("https://news.google.com/rss/search",dict(q=query,hl="en-IN",gl="IN",ceid="IN:en")).content


def ingest(start, end, group="all", engine=None, *, scheduled=False):
    engine = engine or sync_engine()
    boundaries(start,end)
    if (end-start).days > 366:
        raise ValueError("Backfill at most 367 days per command")
    results = []
    for source in SOURCES:
        if group == "media" and source.startswith("NSE ") or group == "nse" and not source.startswith("NSE "):
            continue
        with engine.connect() as lock:
            acquired = lock.execute(text("SELECT pg_try_advisory_lock(hashtext(:key))"),dict(key="company-news:"+source)).scalar()
            lock.commit()
            if not acquired:
                results.append(dict(source=source,status="already_running")); continue
            try:
                with engine.connect() as conn:
                    companies = list(conn.execute(text("SELECT symbol,name,aliases FROM news_companies")).mappings())
                    days = list(days_between(start, end))
                    if scheduled:
                        # Keep polling the latest two days. Older days are complete only
                        # after a successful check made after that IST day ended.
                        complete = set(conn.scalars(text("""
                            SELECT day FROM company_news_coverage
                            WHERE source=:source AND day>=:start AND day<:yesterday
                              AND status IN ('success','limited')
                              AND checked_at >= ((day + 1)::timestamp AT TIME ZONE 'Asia/Kolkata')
                        """), dict(source=source, start=start, yesterday=end-timedelta(days=1))))
                        days = [day for day in reversed(days) if day not in complete]
                for day in days:
                    lo, hi = boundaries(day,day)
                    try:
                        if source.startswith("NSE "):
                            segment = source.split()[1]
                            data = get("https://www.nseindia.in/api/corporate-announcements",dict(index=segment,
                                from_date=day.strftime("%d-%m-%Y"),to_date=day.strftime("%d-%m-%Y"))).json()
                            items = parse_nse(data,segment)
                            status = "partial" if len(data)>=10000 else "success"
                            detail = "Single-day segment request; no pagination advertised." if status=="success" else "Possible source cap; manual verification required."
                        else:
                            if not companies:
                                raise ValueError("Company directory unavailable; run directory refresh")
                            direct = PUBLISHERS[source][1]
                            use_current = day >= datetime.now(IST).date()-timedelta(days=1)
                            try:
                                payload = get(direct).content if direct and use_current else google_feed(source,day)
                                items,rejected = parse_rss(payload,source)
                                if direct and use_current and not any(lo<=r["published_at"]<hi for r in items):
                                    items,rejected = parse_rss(google_feed(source,day),source)
                            except (requests.RequestException, ValueError, ET.ParseError):
                                if not direct or not use_current:
                                    raise
                                items,rejected = parse_rss(google_feed(source,day),source)
                            for item in items:
                                item["symbols"] = matching_companies(item["title"],companies)
                            status = "partial" if rejected else "limited"
                            detail = "Publisher feed/search coverage is limited, not a complete archive."
                            if rejected:
                                detail += f" {rejected} invalid items rejected."
                        items = [r for r in items if lo<=r["published_at"]<hi and r.get("symbols")]
                        with engine.begin() as conn:
                            store_items(conn,items)
                            record_coverage(conn,source,day,status,len(items),detail)
                        results.append(dict(source=source,day=str(day),status=status,count=len(items)))
                    except Exception as exc:
                        with engine.begin() as conn:
                            record_coverage(conn,source,day,"failed",detail=safe_error(exc))
                        results.append(dict(source=source,day=str(day),status="failed",error=safe_error(exc)))
            finally:
                lock.execute(text("SELECT pg_advisory_unlock(hashtext(:key))"),dict(key="company-news:"+source)); lock.commit()
    return results


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start",type=date.fromisoformat)
    parser.add_argument("--end",type=date.fromisoformat)
    parser.add_argument("--group",choices=["all","nse","media"],default="all")
    parser.add_argument("--directory",action="store_true")
    args=parser.parse_args()
    if args.directory:
        print(json.dumps(refresh_directory()))
    if args.start or args.end:
        print(json.dumps(ingest(args.start or args.end,args.end or args.start,args.group)))
    elif not args.directory:
        parser.error("Provide --directory or --start")

if __name__ == "__main__":
    main()
