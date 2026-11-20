# Company News operations

Local page: http://127.0.0.1:3001/news (sign in with an existing QUANTORA account).
This feature uses the existing FastAPI app, PostgreSQL, Redis and Celery. It has no
dependency on Codex, MCP, DefeatBeta, EODHD quota or another portal.

## Installation / migration

Run from the repository root with the normal DATABASE_URL and REDIS_URL configured:

```powershell
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m stock_agents.ingest.company_news --directory
.venv/Scripts/python.exe -m uvicorn stock_agents.api.main:app --host 127.0.0.1 --port 8701
```

In separate terminals, start the managed Celery services and frontend:

```powershell
.venv/Scripts/python.exe -m scripts.run_pipeline_services
$env:NEXT_DIST_DIR='.next-company-news'
pnpm --dir apps/web build
pnpm --dir apps/web start --port 3001
```

The existing local scheduled supervisor starts the news worker along with the
pipeline workers and Beat. Do not start a second Beat. The supervisor uses a
PostgreSQL advisory lock to prevent duplicate supervisors. On Windows use the
provided solo worker; use prefork workers on Linux for production.

For a standalone news worker under another process manager:

```powershell
.venv/Scripts/python.exe -m celery -A stock_agents.jobs.celery_app:app worker -Q quantora-news -n news@%h --pool solo -c 1 -l INFO
```

The existing Beat configuration delivers filings every 300 seconds, media every
900 seconds, and the full directory at 06:15 Asia/Kolkata. Override intervals with
COMPANY_NEWS_NSE_SECONDS and COMPANY_NEWS_MEDIA_SECONDS, then restart Beat.
Both periodic feeds refresh today and yesterday first, then recover missing or
incomplete days in the seven-day News view under each source's advisory lock.
An older day is skipped once it has a successful or limited check after that IST day ended.
Failed sources retry at the next poll; HTTP calls have at most three attempts,
8-second connect and 25-second read timeouts. A long Retry-After ends that poll.
The existing 07:00/18:30 EOD pipelines are unchanged.

## Historical backfill (including the Paytm example)

```powershell
.venv/Scripts/python.exe -m stock_agents.ingest.company_news --start 2026-11-13 --end 2026-11-13 --group nse
```

This fetches the whole main-board and SME segments for that day; then search
PAYTM.NS on /news and enter 2026-11-13 in either date field. It deliberately does
not fetch each company separately. To include historical media:

```powershell
.venv/Scripts/python.exe -m stock_agents.ingest.company_news --start 2026-11-13 --end 2026-11-20 --group all
```

Commands emit source/day status, counts and errors. Review these statuses; a
completed command does not mean every publisher succeeded. Backfill batches are
limited to 367 days. Repeat failed windows safely: (source, source_key) is unique,
and article and company links commit in the same transaction.

## API and storage

- GET /company-news: symbol, kind (all/headline/announcement), source, start, end,
  page, page_size (1–100). Next.js uses the authenticated /backend proxy.
- GET /company-news/companies?q=Paytm: company autocomplete with verified aliases.
- GET /company-news/export.csv: identical filters, no pagination; streams every
  matching row with UTF-8 BOM and spreadsheet-formula escaping.
- All three routes require the existing current user. No public export bypass.
- One date means one IST day. Two dates include both dates. No dates means the
  latest seven IST days. Stored timestamps are timezone-aware; sorting is
  published_at DESC, id DESC. Multi-company stories count once.
- Migration 0012 adds news_companies, news_items, news_item_companies and
  company_news_coverage. The news directory links to symbology where available
  and expands to official NSE main-board/SME lists without activating thousands
  of securities in the existing Nifty research universe.
- Company matching uses full company names and reviewed aliases with word
  boundaries. It does not match arbitrary short ticker words. Add reviewed brand
  aliases to BRANDS in the adapter and refresh the directory when needed.

## Sources and coverage limits

NSE: https://www.nseindia.in/api/corporate-announcements, index=equities and
index=sme, one day per request, without a symbol. The inspected live response was
an array with no advertised pagination metadata. November 13 returned 1,112 and
308 records respectively, so a 1,000-record cap was not observed. A response at
the conservative 10,000-row ceiling is marked partial, never silently complete.
Unadvertised exchange limits cannot be ruled out. The attachment is preserved;
missing attachments link to the official filings page. Stable key is source
(which includes segment) plus seq_id.

- Mint: https://www.livemint.com/rss/companies
- Economic Times: https://economictimes.indiatimes.com/markets/stocks/news/rssfeeds/2146842.cms
- Business Standard: https://www.business-standard.com/rss/markets-106.rss
- Moneycontrol: its direct latestnews.xml feed was stale (August 2024), so uses
  https://news.google.com/rss/search restricted to moneycontrol.com.

Historical media uses publisher-restricted Google News date searches. Publisher
domains are checked against the result's source URL; actual publisher names are
stored. Google delivery links are preserved rather than inventing canonical URLs.
Current direct feeds fall back to Google if unavailable or outside the selected
day. Date searches are widened, then filtered to the exact IST boundaries.
Only metadata is collected. Every media day is labelled limited, because feed
limits, search indexing and company-name matching prevent an exhaustive archive.
No current headline is substituted for an old date.

The UI distinguishes uncollected dates, unavailable/partial sources and collected
results. Expand a source to see its last successful update and error details.
PostgreSQL retains articles and coverage across restarts and Redis eviction.
The frontend polls stored news once a minute; it never fetches publishers directly.

## Diagnostics and validation

Inspect logs/company-news-worker.log, logs/pipeline-beat.log and the source cards
on /news. Source/day details live in company_news_coverage. A worker acknowledgement
is not proof of source success; inspect coverage and the task's returned statuses.

```powershell
.venv/Scripts/python.exe -m pytest tests/test_company_news.py -q
pnpm --dir apps/web exec tsc --noEmit
pnpm --dir apps/web build
```

Set TEST_DATABASE_URL to a PostgreSQL instance on which the test user can create
temporary databases to run integration tests; tests create/drop only isolated test
databases. Parsing, alias matching, IST boundaries, idempotency, transaction rollback,
authorization, multi-company rows, CSV pagination/formula protection, network retries,
partial failures and missing coverage are tested. Fixtures never enter live storage.

## Files

- src/stock_agents/ingest/company_news.py: sources, matching, storage, CLI.
- src/stock_agents/api/company_news.py: filters, list, directory and CSV.
- src/stock_agents/api/main.py: router registration.
- src/stock_agents/storage/alembic/versions/0012_company_news.py: migration.
- src/stock_agents/storage/company_news_models.py and storage/alembic/env.py: schema metadata.
- src/stock_agents/jobs/celery_app.py and scripts/run_pipeline_services.py: schedules/worker.
- apps/web/src/app/news/: page, query workflow, server pagination and CSS.
- apps/web/src/components/shell.tsx: navigation.
- apps/web/src/lib/proxy.ts: authenticated route allowlist.
- tests/test_company_news.py: focused backend tests.
- .env.example: configurable polling intervals.

Live checks on 20 November 2026: all four publishers ingested matched headlines;
both NSE segments and both directory CSVs responded. The Paytm filing seq_id
106858627 was stored at 13-Nov-2026 14:42:39 IST and its PDF returned HTTP 206 with
application/pdf for a range request. November 13 ingestion repeated with the same
1,420 filing count. See docs/verification/company-news-live.json for final checks.

## Individual stock pages

Each `/stocks/{ticker}` page shows the seven newest stored headlines and announcements
for that exact NSE symbol, regardless of publication date, using `/company-news/latest`.
The view refreshes every minute. Older records are retained; the full Company News
page still provides filters, pagination and CSV export. No news records are deleted
by the stock page display limit.

## Homepage news cards

Signed-in homepage visitors see up to 20 latest stories from the current IST day.
The feed refreshes every minute and rolls over the date automatically at midnight IST.
Cards advance every six seconds; hover/focus pauses movement, with pause and arrow
controls, touch scrolling and reduced-motion support. Older news stays in the archive.

## Free financial headline sentiment (20 November 2026 cutover)

Daily news/sentiment stages and legacy admin news/sentiment jobs now use the free
company-news adapter and local ProsusAI/finbert, not EODHD news/sentiment calls.
EODHD fundamentals, estimates and price history are unchanged. Existing EODHD news
and sentiment records are retained for audit but excluded from current sentiment
inputs and the sentiment chart endpoint.

Every 15-minute media task scores newly collected/changed headlines. Both 07:00 and
18:30 daily pipelines fetch company news and run the same sentiment updater. The
model is pinned to revision 0bc2ac10dda6929bcb1f77ccc43c7ec5c424f031. CPU inference
uses two threads. First startup downloads the model; subsequent runs reuse its cache.
Model reference and attribution: https://huggingface.co/ProsusAI/finbert

Labels use the highest probability among positive, negative and neutral.
Polarity = P(positive) - P(negative), in [-1,1]. These are model estimates of the
headline's tone, not verified facts, recommendations or per-company causal impact.
Multi-company stories share the headline estimate. Boilerplate NSE announcements
remain visible but are not sentiment-scored. No full article body is scraped.
Repeated normalized titles are scored once per run and counted once per stock/IST
day. Original stories are retained. Stock-days without matched media remain missing,
not fabricated neutral observations. Current free feeds are not exhaustive.

company_news_sentiment stores model revision, title hash, probabilities and scoring
time. sentiment_daily uses source=free_news_finbert and an actual known_date, never
backdated to publication. Historical backtests therefore do not see today's newly
scored observations. Writes are transactional; model failure rolls back the batch.
Concurrent daily/periodic updates wait up to 60 seconds for the sentiment lock.

Manual scoring and full data validation/dump:

```powershell
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m stock_agents.ingest.free_sentiment
.venv/Scripts/python.exe -m scripts.audit_company_sentiment
```

The audit writes docs/verification/free-news-sentiment.csv and
free-news-sentiment-audit.json. It checks every stored media headline for valid
probabilities, title hashes, company mappings, timestamps, model version and source
key uniqueness. Headlines/stock-page/homepage show a FinBERT estimate; the Company
News CSV includes polarity and model provenance. A headline's absence is not proof
that no news exists for that company.

The scoring failure from duplicate price vendors on a stock/date was fixed by
selecting one deterministic source before pivoting; raw vendor prices were retained.
Missing Angel One adjusted closes are a separate validation warning, not repaired
or relabelled by this news/sentiment change.

## Coverage expansion and alternative factors

Company-specific Google News discovery supplements the four publisher-wide feeds.
Only articles verified against those publisher domains and matched using the company
directory are accepted. A rotating batch of 25 least-recently-checked Nifty 500/F&O
companies runs after each 15-minute media poll. The search covers seven days; at
501 companies a complete rotation takes about 5.25 hours when services stay running.
Requests are paced to at most one new search per second, with three bounded workers.
Company search status is stored as `Company search SYMBOL` in company_news_coverage.
Run a catch-up with `python -m stock_agents.ingest.company_search --limit 501`.

News attention (7-day) counts matched, deduplicated headlines. It is not social buzz.
Social buzz stays disabled/unavailable without a verified social API. Short interest
also stays unavailable; the separate NSE short-sales/volume factor is enabled by
default (weight 3). It measures trading activity, not outstanding short positions.
Previously saved custom weights are not forcibly overwritten.

News volume compares the last three days with the preceding 27 days only when all
four publisher/day collection checks exist for the full 30-day window. Publisher
coverage remains limited, so this measures the collected feed, not all news globally.
Zero recent matched stories over a positive checked baseline yields zero; no baseline
stays missing. An initial 30-day media and 90-day insider backfill was performed.
Insider records only include qualifying disclosed market purchases/sales. Absence
of a qualifying trade is not filled with a fabricated transaction or zero signal.

Coverage verification, 20 November 2026 at 14:05 IST: all 501 research-universe
companies searched, including the three REIT identities from verified NSE index
reference data. The 120 publisher/day checks for the 30-day baseline completed
with limited-feed status and no failures. All 2,173 stored media headlines passed
score/hash/timestamp/company/source validation. Nifty 500 coverage: seven-day
sentiment/attention 299, news-volume ratio 296, insider activity 51, NSE short-sales
activity 488. The 90-day insider refresh fetched 435 filings, found 477 qualifying
trade records and inserted seven previously absent records without fetch failures.

Run `python -m scripts.audit_news_expansion` for an updated per-stock CSV and summary.
The live dashboard polls latest-date rankings every minute; historical-date views
remain fixed. Scoring only uses observations actually known by the selected date.
