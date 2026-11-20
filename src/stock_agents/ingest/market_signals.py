"""Independent, audited Nifty 500 alternative-data ingestion. See --help."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from urllib.parse import quote

import requests
from sqlalchemy import text

from stock_agents.common.config import load_settings
from stock_agents.ingest.company_news import (
    IST,
    boundaries,
    company_aliases,
    matching_companies,
    normalize_symbol,
)
from stock_agents.jobs.queue import sync_engine

UNIVERSE_URL = "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv"
NSE_URL = "https://www.nseindia.in/api/historicalOR/bulk-block-short-deals"
HN_URL = "https://hn.algolia.com/api/v1/search_by_date"
SOURCES = ("nse_short_sales", "ortex", "publisher_buzz", "hacker_news")
BUZZ = re.compile(
    r"\b(social media|viral|backlash|trending on|on X|on Reddit|netizens|online reactions|social campaign)\b",
    re.I,
)


class SourceUnavailable(Exception):
    pass


class BudgetExceeded(Exception):
    pass


class IncompleteWindow(Exception):
    pass


def buzz_title(title):
    return bool(BUZZ.search(title))


def signal_companies(members):
    """Use distinctive brands where the legal name is also an ordinary phrase."""
    precise = {
        "BBOX": [
            "black box limited",
            "black box ltd",
            "black box corporation",
            "black box network",
        ],
        "MEDANTA": ["medanta", "global health limited", "global health ltd"],
        "ETERNAL": ["eternal limited", "eternal ltd", "zomato", "blinkit"],
        "VEDL": ["vedanta limited", "vedanta ltd", "vedanta resources", "vedanta group"],
        "NAVA": ["nava limited", "nava ltd", "nava bharat"],
        "ASTRAL": ["astral limited", "astral ltd", "astral pipes", "astral adhesives"],
    }
    return [
        {
            "symbol": r["ticker"],
            "aliases": precise.get(r["ticker"], company_aliases(r["ticker"], r["company_name"])),
        }
        for r in members
    ]


def signal_matches(title, companies):
    matches = matching_companies(title, companies)
    if re.search(r"\b(?:haber[ -]bosch|hieronymus bosch)\b", title, re.I):
        matches = [s for s in matches if s != "BOSCHLTD"]
    return matches


class Client:
    """Fixed provider URLs; credentials only in headers, never error messages."""

    def __init__(self, budget=300):
        self.budget = budget
        self.used = 0

    def get(self, url, params=None, headers=None):
        for attempt in range(3):
            if self.used >= self.budget:
                raise BudgetExceeded("Configured provider request budget exhausted")
            self.used += 1
            try:
                r = requests.get(
                    url,
                    params=params,
                    headers={"User-Agent": "QUANTORA personal research/1.0", **(headers or {})},
                    timeout=(8, 30),
                )
            except requests.RequestException:
                if attempt == 2:
                    raise SourceUnavailable("Network request failed") from None
                time.sleep(2**attempt)
                continue
            if r.status_code in (401, 402, 403, 404):
                raise SourceUnavailable(
                    f"Provider HTTP {r.status_code}: access, entitlement, credits or listing unavailable"
                )
            if r.status_code == 429 or r.status_code >= 500:
                retry = r.headers.get("Retry-After", "2")
                delay = int(retry) if retry.isdigit() else 30
                if attempt == 2 or delay > 30:
                    raise SourceUnavailable(f"Provider HTTP {r.status_code}: retry later")
                time.sleep(max(delay, 2**attempt))
                continue
            if r.status_code != 200:
                raise SourceUnavailable(f"Provider HTTP {r.status_code}")
            if len(r.content) > 30_000_000:
                raise ValueError("Oversized provider payload")
            return r
        raise SourceUnavailable("Provider request did not complete")


def parse_universe(payload):
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
    reader.fieldnames = [x.strip() for x in reader.fieldnames or []]
    if not {"Company Name", "Symbol", "ISIN Code", "Series"} <= set(reader.fieldnames):
        raise ValueError("Malformed Nifty 500 headers")
    rows = []
    for r in reader:
        row = dict(
            ticker=r["Symbol"].strip().upper(),
            company_name=r["Company Name"].strip(),
            isin=r["ISIN Code"].strip(),
            series=r["Series"].strip(),
        )
        # The official file can contain corporate-action placeholders, not securities.
        if (
            row["ticker"].startswith("DUMMY")
            and row["company_name"].lower().startswith("dummy ")
            and row["isin"].startswith("DUM")
        ):
            continue
        if not all(row.values()) or not re.fullmatch(r"IN[A-Z0-9]{10}", row["isin"]):
            raise ValueError("Invalid constituent identity")
        rows.append(row)
    if (
        len(rows) != 500
        or len({r["ticker"] for r in rows}) != 500
        or len({r["isin"] for r in rows}) != 500
    ):
        raise ValueError("Expected 500 unique symbols and ISINs; prior membership preserved")
    return rows


def safe_reason(exc):
    if isinstance(exc, (SourceUnavailable, BudgetExceeded, IncompleteWindow)):
        return str(exc)
    return type(exc).__name__ + ": provider/schema validation failed"


def start_run(engine, source, start, end, snapshot=None, ticker=None):
    run_id = str(uuid.uuid4())
    with engine.begin() as c:
        c.execute(
            text("""INSERT INTO market_signal_runs(id,source,ticker,start_date,end_date,snapshot_id,status,started_at)
          VALUES (:id,:source,:ticker,:start,:end,:snapshot,'running',:now)"""),
            dict(
                id=run_id,
                source=source,
                ticker=ticker,
                start=start,
                end=end,
                snapshot=snapshot,
                now=datetime.now(UTC),
            ),
        )
    return run_id


def finish_run(c, run_id, status, fetched=0, inserted=0, updated=0, reason="", details=None):
    c.execute(
        text("""UPDATE market_signal_runs SET status=:status,finished_at=:now,rows_fetched=:fetched,
      rows_inserted=:inserted,rows_updated=:updated,reason=:reason,details=CAST(:details AS jsonb) WHERE id=:id"""),
        dict(
            id=run_id,
            status=status,
            now=datetime.now(UTC),
            fetched=fetched,
            inserted=inserted,
            updated=updated,
            reason=reason,
            details=json.dumps(details or {}),
        ),
    )


def sync_constituents(engine=None, client=None):
    engine = engine or sync_engine()
    today = datetime.now(IST).date()
    rid = start_run(engine, "universe", today, today)
    try:
        payload = (client or Client(3)).get(UNIVERSE_URL).content
        rows = parse_universe(payload)
        digest = hashlib.sha256(payload).hexdigest()
        now = datetime.now(UTC)
        with engine.begin() as c:
            c.execute(text("SELECT pg_advisory_xact_lock(490122896)"))
            inserted = 0
            for row in rows:
                c.execute(
                    text(
                        "INSERT INTO symbology(ticker,active) VALUES (:ticker,true) ON CONFLICT(ticker) DO UPDATE SET active=true"
                    ),
                    row,
                )
                c.execute(
                    text("""INSERT INTO company_reference(ticker,company_name,isin,venue,series,source,observed_on)
                  VALUES (:ticker,:company_name,:isin,'NSE',:series,'nse_indices',:today)
                  ON CONFLICT(ticker) DO UPDATE SET company_name=EXCLUDED.company_name,isin=EXCLUDED.isin,
                  series=EXCLUDED.series,source=EXCLUDED.source,observed_on=EXCLUDED.observed_on"""),
                    {**row, "today": today},
                )
            snapshot = c.scalar(
                text("""INSERT INTO research_universe_snapshots
              VALUES (:id,:day,:now,:url,:hash,500) ON CONFLICT(observed_on,content_hash)
              DO UPDATE SET content_hash=EXCLUDED.content_hash RETURNING id"""),
                dict(id=str(uuid.uuid4()), day=today, now=now, url=UNIVERSE_URL, hash=digest),
            )
            for row in rows:
                inserted += c.execute(
                    text("""INSERT INTO research_universe_members VALUES (:snapshot,:ticker,:company_name,:isin,:series)
                  ON CONFLICT(snapshot_id,ticker) DO NOTHING"""),
                    {**row, "snapshot": snapshot},
                ).rowcount
            from stock_agents.ingest.daily import _membership

            _membership(c, {"NIFTY500": {r["ticker"] for r in rows}}, today)
            finish_run(
                c,
                rid,
                "success",
                fetched=500,
                inserted=inserted,
                reason="Validated current constituent snapshot; no historical membership inferred",
                details={
                    "snapshot_id": snapshot,
                    "excluded_placeholders": [
                        r["Symbol"].strip()
                        for r in csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
                        if r["Symbol"].strip().startswith("DUMMY")
                    ],
                },
            )
        return {"status": "success", "snapshot_id": snapshot, "constituents": 500, "run_id": rid}
    except Exception as exc:
        with engine.begin() as c:
            finish_run(c, rid, "failed", reason=safe_reason(exc))
        raise


def current_universe(engine):
    with engine.connect() as c:
        snapshot = c.scalar(
            text("SELECT id FROM research_universe_snapshots ORDER BY retrieved_at DESC LIMIT 1")
        )
        if not snapshot:
            raise ValueError("Sync validated constituents first")
        rows = [
            dict(r)
            for r in c.execute(
                text(
                    "SELECT * FROM research_universe_members WHERE snapshot_id=:id ORDER BY ticker"
                ),
                {"id": snapshot},
            ).mappings()
        ]
    return snapshot, rows


def parse_short_sales(payload, start, end):
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
    reader.fieldnames = [x.strip() for x in reader.fieldnames or []]
    if not {"Date", "Symbol", "Security Name", "Quantity"} <= set(reader.fieldnames):
        raise ValueError("Invalid NSE short-sales CSV headers")
    rows = {}
    for row in reader:
        day = datetime.strptime(row["Date"].strip(), "%d-%b-%Y").date()
        ticker = normalize_symbol(row["Symbol"])
        qty = row["Quantity"].replace(",", "").strip()
        if not ticker or not re.fullmatch(r"\d+", qty):
            raise ValueError("Invalid short-sale row")
        if not start <= day <= end:
            raise ValueError("NSE row outside requested trade dates")
        key = (ticker, day)
        if key in rows:
            raise ValueError("Duplicate NSE stock/date disclosure")
        rows[key] = dict(ticker=ticker, trade_date=day, short_sale_shares=int(qty))
    return list(rows.values())


def parse_ortex(payload, start, end):
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("Invalid ORTEX response")
    rows = []
    for raw in payload["data"]:
        day = date.fromisoformat(raw["date"])
        if not start <= day <= end:
            raise ValueError("ORTEX date outside requested window")
        values = {}
        for field, key in [
            ("siShares", "short_interest_shares"),
            ("siPctFreeFloat", "short_interest_pct_free_float"),
        ]:
            value = raw.get(field)
            if value is not None:
                value = float(value)
                if not math.isfinite(value) or value < 0:
                    raise ValueError("Invalid ORTEX estimate")
            values[key] = value
        if any(v is not None for v in values.values()):
            rows.append(dict(observation_date=day, **values))
    return rows


def fetch_hn(lo, hi, fetch):
    """Return all stories in [lo,hi); split capped windows before paginating."""
    params = {
        "tags": "story",
        "hitsPerPage": 1000,
        "page": 0,
        "numericFilters": f"created_at_i>={lo},created_at_i<{hi}",
    }
    data = fetch(params)
    count = int(data["nbHits"])
    pages = int(data["nbPages"])
    exhaustive = data.get("exhaustiveNbHits", data.get("exhaustive", {}).get("nbHits", True))
    if count >= 1000 or count > pages * 1000 or not exhaustive:
        if hi - lo <= 1:
            raise IncompleteWindow("HN result cap reached within one second")
        middle = (lo + hi) // 2
        return fetch_hn(lo, middle, fetch) + fetch_hn(middle, hi, fetch)
    if pages > 100:
        raise IncompleteWindow("Unexpected HN page count")
    rows = list(data["hits"])
    for page in range(1, pages):
        more = fetch({**params, "page": page})
        if int(more["nbHits"]) != count:
            raise IncompleteWindow("HN window changed during pagination; retry")
        rows.extend(more["hits"])
    ids = [str(r["objectID"]) for r in rows]
    if len(ids) != len(set(ids)) or len(ids) != count:
        raise IncompleteWindow("HN pagination omitted or repeated stories")
    if any(not lo <= int(r["created_at_i"]) < hi for r in rows):
        raise ValueError("HN timestamp outside requested window")
    return rows


def upsert(c, table, keys, values, changes):
    """Return inserted/changed counts; retrieval-only refresh is not a data change."""
    where = " AND ".join(f"{key}=:{key}" for key in keys)
    previous = c.execute(text(f"SELECT * FROM {table} WHERE {where}"), values).mappings().first()
    columns = ",".join(values)
    binds = ",".join(":" + k for k in values)
    updates = ",".join(f"{k}=EXCLUDED.{k}" for k in values if k not in keys)
    c.execute(
        text(
            f"INSERT INTO {table} ({columns}) VALUES ({binds}) ON CONFLICT({','.join(keys)}) DO UPDATE SET {updates}"
        ),
        values,
    )
    return (1, 0) if previous is None else (0, int(any(previous[k] != values[k] for k in changes)))


def store_posts(c, hits, companies, run_id, now):
    inserted = updated = 0
    existing = set(c.scalars(text("SELECT hn_item_id FROM public_social_posts")))
    for hit in hits:
        title = (hit.get("title") or "").strip()
        symbols = signal_matches(title, companies)
        if not symbols or not title:
            if str(hit["objectID"]).isdecimal() and int(hit["objectID"]) in existing:
                c.execute(
                    text("DELETE FROM public_social_post_companies WHERE hn_item_id=:id"),
                    {"id": int(hit["objectID"])},
                )
                c.execute(
                    text("DELETE FROM public_social_posts WHERE hn_item_id=:id"),
                    {"id": int(hit["objectID"])},
                )
            continue
        item_id = str(hit["objectID"])
        if not item_id.isdecimal():
            raise ValueError("Invalid HN item identifier")
        values = dict(
            hn_item_id=int(item_id),
            title=title,
            discussion_url="https://news.ycombinator.com/item?id=" + item_id,
            published_at=datetime.fromtimestamp(int(hit["created_at_i"]), UTC),
            points=hit.get("points"),
            comment_count=hit.get("num_comments"),
            retrieved_at=now,
            engagement_observed_at=now,
            run_id=run_id,
        )
        for k in ("points", "comment_count"):
            if values[k] is not None and (not isinstance(values[k], int) or values[k] < 0):
                raise ValueError("Invalid engagement count")
        a, b = upsert(
            c, "public_social_posts", ["hn_item_id"], values, ["title", "points", "comment_count"]
        )
        inserted += a
        updated += b
        # Replace this post's derived matches transactionally if its title changes.
        c.execute(
            text("DELETE FROM public_social_post_companies WHERE hn_item_id=:id"),
            {"id": int(item_id)},
        )
        for symbol in symbols:
            c.execute(
                text("INSERT INTO public_social_post_companies VALUES (:id,:ticker)"),
                {"id": int(item_id), "ticker": symbol},
            )
    return inserted, updated


def run_source(engine, source, start, end, snapshot, members, symbol=None):
    rid = start_run(engine, source, start, end, snapshot, symbol)
    selected = [r for r in members if not symbol or r["ticker"] == symbol]
    symbols = {r["ticker"] for r in selected}
    companies = signal_companies(members)
    fetched = inserted = updated = 0
    details = {}
    now = datetime.now(UTC)
    status = "success"
    reason = ""
    try:
        if source == "nse_short_sales":
            client = Client(6)
            response = client.get(
                NSE_URL,
                {
                    "optionType": "short_selling",
                    "csv": "true",
                    "from": start.strftime("%d-%m-%Y"),
                    "to": end.strftime("%d-%m-%Y"),
                },
            )
            rows = parse_short_sales(response.content, start, end)
            fetched = len(rows)
            now = datetime.now(UTC)
            with engine.begin() as c:
                for row in rows:
                    if row["ticker"] in symbols:
                        a, b = upsert(
                            c,
                            "short_sale_observations",
                            ["ticker", "trade_date"],
                            dict(
                                **row,
                                source="NSE historical short selling",
                                retrieved_at=now,
                                run_id=rid,
                            ),
                            ["short_sale_shares"],
                        )
                        inserted += a
                        updated += b
                finish_run(
                    c,
                    rid,
                    "success",
                    fetched,
                    inserted,
                    updated,
                    "Missing disclosure is not a zero",
                    {"requests": client.used, "market_wide": True},
                )
        elif source == "hacker_news":
            client = Client(int(load_settings().env("HN_REQUEST_BUDGET", "300")))
            lo, hi = boundaries(start, end)
            hits = fetch_hn(
                int(lo.timestamp()), int(hi.timestamp()), lambda p: client.get(HN_URL, p).json()
            )
            fetched = len(hits)
            now = datetime.now(UTC)
            if symbol:
                hits = [
                    h for h in hits if symbol in signal_matches(h.get("title") or "", companies)
                ]
            with engine.begin() as c:
                inserted, updated = store_posts(c, hits, companies, rid, now)
                finish_run(
                    c,
                    rid,
                    "success",
                    fetched,
                    inserted,
                    updated,
                    "HN stories only; not all social networks",
                    {"requests": client.used, "market_wide": True},
                )
        elif source == "publisher_buzz":
            from stock_agents.ingest.company_news import ingest

            coverage = ingest(start, end, "media", engine)
            now = datetime.now(UTC)
            status = (
                "partial"
                if any(r["status"] not in ("success", "limited") for r in coverage)
                else "limited"
            )
            lo, hi = boundaries(start, end)
            with engine.begin() as c:
                rows = (
                    c.execute(
                        text(
                            "SELECT id,title FROM news_items WHERE kind='headline' AND published_at>=:lo AND published_at<:hi AND source IN ('Mint','The Economic Times','Moneycontrol','Business Standard')"
                        ),
                        {"lo": lo, "hi": hi},
                    )
                    .mappings()
                    .all()
                )
                fetched = len(rows)
                for row in rows:
                    if not buzz_title(row["title"]):
                        continue
                    matches = signal_matches(row["title"], companies)
                    if not matches or (symbol and symbol not in matches):
                        continue
                    a, b = upsert(
                        c,
                        "publisher_buzz",
                        ["news_item_id"],
                        dict(
                            news_item_id=row["id"],
                            rule_version="social-headline-v1",
                            retrieved_at=now,
                            run_id=rid,
                        ),
                        ["rule_version"],
                    )
                    inserted += a
                    updated += b
                    for ticker in matches:
                        c.execute(
                            text(
                                "INSERT INTO publisher_buzz_companies VALUES (:id,:ticker) ON CONFLICT DO NOTHING"
                            ),
                            {"id": row["id"], "ticker": ticker},
                        )
                finish_run(
                    c,
                    rid,
                    status,
                    fetched,
                    inserted,
                    updated,
                    "Publisher/search coverage is limited; headline rule, not measured social engagement",
                    {"sources": coverage},
                )
        elif source == "ortex":
            key = load_settings().env("ORTEX_API_KEY")
            if not key:
                raise SourceUnavailable(
                    "ORTEX_API_KEY not configured; no outstanding estimates collected"
                )
            client = Client(int(load_settings().env("ORTEX_REQUEST_BUDGET", "50")))
            # Rotate a budget-limited subscription toward least recently attempted listings.
            with engine.connect() as c:
                seen = dict(
                    c.execute(
                        text(
                            "SELECT key,max(started_at) FROM market_signal_runs r CROSS JOIN LATERAL jsonb_object_keys(r.details) key WHERE source='ortex' GROUP BY key"
                        )
                    ).all()
                )
            selected.sort(
                key=lambda r: (seen.get(r["ticker"], datetime.min.replace(tzinfo=UTC)), r["ticker"])
            )
            for member in selected:
                ticker = member["ticker"]
                page = 1
                rows = []
                try:
                    while True:
                        payload = client.get(
                            f"https://api.ortex.com/api/v11/stock/NSEI/{quote(ticker, safe='')}/short/short_interest/",
                            {
                                "from_date": start.isoformat(),
                                "to_date": end.isoformat(),
                                "page": page,
                                "split_adjusted": "false",
                            },
                            headers={"Ortex-Api-Key": key},
                        ).json()
                        records = parse_ortex(payload, start, end)
                        rows.extend(records)
                        fetched += len(records)
                        if payload.get("meta", {}).get("restriction"):
                            details[ticker] = "Provider restricted window"
                            status = "partial"
                        if not payload.get("pagination", {}).get("next"):
                            break
                        page += 1
                        if page > 1000:
                            raise IncompleteWindow("ORTEX pagination exceeded safety limit")
                    now = datetime.now(UTC)
                    with engine.begin() as c:
                        for row in rows:
                            a, b = upsert(
                                c,
                                "short_interest_estimates",
                                ["ticker", "observation_date", "source"],
                                dict(
                                    ticker=ticker,
                                    source="ORTEX",
                                    **row,
                                    retrieved_at=now,
                                    run_id=rid,
                                ),
                                ["short_interest_shares", "short_interest_pct_free_float"],
                            )
                            inserted += a
                            updated += b
                    details.setdefault(ticker, "collected" if rows else "No estimate supplied")
                except (SourceUnavailable, BudgetExceeded, IncompleteWindow) as exc:
                    details[ticker] = safe_reason(exc)
                    status = "partial"
                    if isinstance(exc, BudgetExceeded) or any(
                        f"HTTP {code}" in str(exc) for code in (401, 402, 403, 429)
                    ):
                        break
            pending = [r["ticker"] for r in selected if r["ticker"] not in details]
            if pending:
                details["_not_requested"] = pending
                status = "partial"
            details["_requests"] = client.used
            with engine.begin() as c:
                finish_run(
                    c,
                    rid,
                    status,
                    fetched,
                    inserted,
                    updated,
                    "Provider estimates only; no inference from daily short sales",
                    details,
                )
        else:
            raise ValueError("Unknown provider")
    except Exception as exc:
        status = (
            "unavailable"
            if isinstance(exc, SourceUnavailable)
            else "partial"
            if isinstance(exc, (BudgetExceeded, IncompleteWindow))
            else "failed"
        )
        if source != "ortex":
            inserted = updated = 0  # Source transaction rolled back.
        reason = safe_reason(exc)
        with engine.begin() as c:
            finish_run(c, rid, status, fetched, inserted, updated, reason, details)
    with engine.connect() as c:
        return dict(
            c.execute(text("SELECT * FROM market_signal_runs WHERE id=:id"), {"id": rid})
            .mappings()
            .one()
        )


def backfill(start, end, symbol=None, sources=SOURCES, engine=None):
    if not start <= end <= datetime.now(IST).date() or (end - start).days > 366:
        raise ValueError("Choose an inclusive past/present range of at most 367 days")
    if not sources or any(source not in SOURCES for source in sources):
        raise ValueError("Choose known sources")
    engine = engine or sync_engine()
    snapshot, members = current_universe(engine)
    symbol = normalize_symbol(symbol) if symbol else None
    if symbol and symbol not in {r["ticker"] for r in members}:
        raise ValueError("Symbol is not in the current validated Nifty 500 snapshot")
    results = []
    for source in sources:
        if source not in SOURCES:
            raise ValueError("Unknown source")
        with engine.connect() as lock:
            acquired = lock.scalar(
                text("SELECT pg_try_advisory_lock(hashtext(:key))"),
                {"key": "market-signals:" + source},
            )
            lock.commit()
            if not acquired:
                rid = start_run(engine, source, start, end, snapshot, symbol)
                with engine.begin() as c:
                    finish_run(
                        c, rid, "already_running", reason="Another source ingestion holds its lock"
                    )
                results.append({"id": rid, "source": source, "status": "already_running"})
                continue
            try:
                # Holding the session lock proves no earlier worker can still own this source.
                with engine.begin() as c:
                    c.execute(
                        text(
                            "UPDATE market_signal_runs SET status='interrupted',finished_at=now(),reason='Previous worker ended before completing; retry supersedes this attempt' WHERE source=:source AND status='running'"
                        ),
                        {"source": source},
                    )
                results.append(run_source(engine, source, start, end, snapshot, members, symbol))
            finally:
                lock.execute(
                    text("SELECT pg_advisory_unlock(hashtext(:key))"),
                    {"key": "market-signals:" + source},
                )
                lock.commit()
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["sync", "backfill", "incremental", "diagnose"])
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    parser.add_argument("--symbol")
    parser.add_argument("--sources", default=",".join(SOURCES))
    args = parser.parse_args()
    engine = sync_engine()
    # CLI writes only to an explicitly identifiable local development database.
    if engine.url.host not in ("127.0.0.1", "localhost", "::1") or not any(
        x in (engine.url.database or "").lower() for x in ("local", "dev", "test")
    ):
        parser.error("A named local/development PostgreSQL target is required before writing")
    if args.command == "sync":
        result = sync_constituents(engine)
    else:
        if args.command == "diagnose" and not args.symbol:
            parser.error("diagnose requires --symbol")
        today = datetime.now(IST).date()
        start = args.start or today - timedelta(days=6 if args.command == "incremental" else 29)
        end = args.end or today
        result = backfill(start, end, args.symbol, args.sources.split(","), engine)
    print(json.dumps(result, default=str))


if __name__ == "__main__":
    main()
