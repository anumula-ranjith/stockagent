"""Free Economic Times RSS headlines for the owner's personal research.

Only headline metadata is stored. Publisher links and attribution are retained.
No API key, full-article scraping, or inferred sentiment is used.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import time
import uuid
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from stock_agents.storage.postgres import Base

SOURCE = "The Economic Times RSS"
FEEDS = {
    "stocks": "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
    "companies": "https://economictimes.indiatimes.com/news/company/rssfeeds/2143429.cms",
    "industry": "https://economictimes.indiatimes.com/industry/rssfeeds/13352306.cms",
    "technology": "https://economictimes.indiatimes.com/tech/rssfeeds/13357270.cms",
}
AMBIGUOUS = {"IDEA", "INDIA", "POWER", "NETWORK", "FORCE", "CASTROL", "ONE", "ABC", "GOLD", "STAR"}


def normalize(value):
    return re.sub(r"[^a-z0-9]+", " ", value.casefold().replace("&", " and ")).strip()


def aliases(ticker, company_name):
    name = re.sub(r"\s+(?:limited|ltd\.?|ltd\.?)$", "", (company_name or "").strip(), flags=re.I)
    name = normalize(name)
    names = {name} if len(name) >= 4 and name.upper() not in AMBIGUOUS else set()
    # Common published abbreviations; never a broad group-name match.
    extra = {"SBIN": "SBI", "LT": "L&T", "TCS": "Tata Consultancy Services",
             "M&M": "Mahindra and Mahindra", "INFY": "Infosys", "ADANIPORTS": "Adani Ports",
             "TATAPOWER": "Tata Power", "BHARTIARTL": "Bharti Airtel", "BAJAJ-AUTO": "Bajaj Auto",
             "HINDUNILVR": "Hindustan Unilever", "MARUTI": "Maruti Suzuki", "RELIANCE": "Reliance Industries",
             "SUNPHARMA": "Sun Pharma", "DRREDDY": "Dr Reddy", "ONGC": "ONGC", "LICI": "LIC"}
    if ticker in extra:
        names.add(normalize(extra[ticker]))
    return names, ticker


def matches(headline, identity):
    names, ticker = identity
    normalized = " " + normalize(headline) + " "
    # Subsidiary names must not automatically attach news to the parent ticker.
    specific = normalized
    if ticker == "SBIN":
        specific = re.sub(r"\bsbi (?:life|cards?)\b", "", specific)
    elif ticker == "LT":
        specific = re.sub(r"\bl and t (?:finance|technology|tech)\b", "", specific)
    elif ticker == "LICI":
        specific = re.sub(r"\blic housing\b", "", specific)
    if any(" " + name + " " in specific for name in names):
        return True
    # Uppercase boundaries avoid English words and partial ticker matches.
    return bool(ticker not in AMBIGUOUS and len(ticker) >= 3 and
                re.search(r"(?<![A-Za-z0-9])" + re.escape(ticker) + r"(?![A-Za-z0-9])", headline))


def parse_feed(payload: bytes, now: datetime):
    if len(payload) > 2_000_000 or b"<!DOCTYPE" in payload.upper() or b"<!ENTITY" in payload.upper():
        raise ValueError("Unsupported RSS document")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        raise ValueError("Invalid RSS XML") from None
    if root.tag != "rss" or root.find("channel") is None:
        raise ValueError("Expected RSS feed")
    items, rejected = [], 0
    for item in root.findall("./channel/item"):
        title = html.unescape(item.findtext("title") or "").strip()
        try:
            url = urlsplit((item.findtext("link") or "").strip())
            published = parsedate_to_datetime(item.findtext("pubDate") or "")
            if published.tzinfo is None:
                raise ValueError("Missing timezone")
            published = published.astimezone(UTC)
            if published < now - timedelta(days=30):
                continue
            if published > now + timedelta(minutes=10):
                raise ValueError("Future publication date")
            if not title or len(title) > 500 or url.scheme not in ("https", "http") or url.username or url.password:
                raise ValueError("Invalid metadata")
            if url.hostname != "economictimes.indiatimes.com":
                raise ValueError("Unexpected publisher")
            query = urlencode([(k, v) for k, v in parse_qsl(url.query) if not k.lower().startswith("utm_") and k not in ("from", "source")])
            canonical = urlunsplit((url.scheme, url.netloc, url.path, query, ""))
            if len(canonical) > 1000:
                raise ValueError("URL too long")
        except (ValueError, TypeError, OverflowError):
            rejected += 1
            continue
        items.append(dict(headline=title, url=canonical, published_at=published, source=SOURCE, polarity=None))
    return items, rejected


def fetch_feed(url, now):
    for attempt in range(2):
        try:
            with httpx.Client(timeout=httpx.Timeout(15, connect=6), follow_redirects=False,
                              headers={"User-Agent": "QUANTORA-PersonalResearch/1.0", "Accept": "application/rss+xml, text/xml"}) as client:
                with client.stream("GET", url) as response:
                    response.raise_for_status()
                    payload = bytearray()
                    for chunk in response.iter_bytes():
                        payload.extend(chunk)
                        if len(payload) > 2_000_000:
                            raise ValueError("RSS exceeds size limit")
            return parse_feed(bytes(payload), now)
        except (httpx.HTTPError, ValueError):
            if attempt:
                raise
            time.sleep(1)


def ingest_free_news(conn):
    now = datetime.now(UTC)
    today = now.astimezone(ZoneInfo("Asia/Kolkata")).date()
    members = conn.execute(text("""SELECT s.ticker,c.company_name FROM symbology s
        LEFT JOIN company_reference c USING(ticker) WHERE s.active AND EXISTS
        (SELECT 1 FROM index_membership m WHERE m.ticker=s.ticker
         AND m.index_code IN ('NIFTY500','NSE_FO') AND m.joined_on<=:day AND m.known_on<=:day
         AND (m.left_on IS NULL OR m.left_on>:day)) ORDER BY s.ticker"""), {"day": today}).all()
    if not members:
        raise RuntimeError("News universe is empty")
    identities = [(ticker, aliases(ticker, name)) for ticker, name in members]
    failures, results, unique = {}, {}, {}

    def fetch(entry):
        label, url = entry
        try:
            items, rejected = fetch_feed(url, now)
            return label, items, rejected, None
        except (httpx.HTTPError, ValueError) as exc:
            return label, [], 0, type(exc).__name__

    with ThreadPoolExecutor(max_workers=4) as pool:
        for label, items, rejected, error in pool.map(fetch, FEEDS.items()):
            results[label] = {"items": len(items), "rejected": rejected, "status": "failed" if error else "ok"}
            if error:
                failures[label] = error
            elif rejected:
                failures[label] = "Invalid or stale entries rejected"
            for item in items:
                unique.setdefault(item["url"], item)
    rows, covered = [], set()
    for item in unique.values():
        for ticker, identity in identities:
            if matches(item["headline"], identity):
                covered.add(ticker)
                key = hashlib.sha256((ticker + "|" + item["url"]).encode()).hexdigest()[:24]
                rows.append(dict(item, news_id=key, ticker=ticker, known_date=today))
    written = 0
    if rows:
        table = Base.metadata.tables["news"]
        written = conn.execute(insert(table).values(rows).on_conflict_do_nothing(index_elements=[table.c.news_id])).rowcount
    result = {"status": "partial" if failures else "ok", "members": len(members), "feeds": results,
              "feeds_ok": sum(r["status"] == "ok" for r in results.values()), "feeds_total": len(FEEDS),
              "articles": len(unique), "matched_stocks": len(covered), "stocks_without_recent_matches": len(members)-len(covered),
              "rows": written, "duplicates": len(rows)-written, "errors": failures, "updated_at": now.isoformat()}
    if not result["feeds_ok"]:
        result["status"] = "failed"
    log = Base.metadata.tables["run_log"]
    conn.execute(insert(log).values(run_id="free-news-"+uuid.uuid4().hex, job="free_news", started_at=now.replace(tzinfo=None),
        ended_at=datetime.now(UTC).replace(tzinfo=None), status=result["status"], rows_written=written, warnings=json.dumps(result)))
    return result
