# Build prompt: Four-Agent US Stock Ranking, Portfolio and Backtesting System

This is the authoritative spec for the `stock-agents` rebuild. All phases, data
sources, factor formulas and acceptance criteria live here. If the code and
this document disagree on a factor or an endpoint, this document wins unless a
later `docs/DATA_NOTES.md` entry explicitly supersedes it with an API response
or an entitlement note.

---

## 0. Ground rules

1. **Never invent an API endpoint, parameter or field name.** Before writing a
   loader, write a probe script (`scripts/probe_<source>.py`) that calls the
   endpoint with my key, prints the raw response, and saves it to
   `tests/fixtures/<source>_<endpoint>.json`. Build parsers from the saved
   fixture, not from memory. If documentation and the response disagree, trust
   the response and note it in `docs/DATA_NOTES.md`.
2. **Respect entitlements.** FactSet access covers only licensed products. If
   a FactSet call returns 401/403 or "not entitled", do not fail the pipeline:
   implement the interface, return an empty frame, log a WARNING once per run,
   and let the affected factor fall back as described in Section 3.
3. **Point-in-time everywhere.** Every stored fact carries `effective_date`
   (the date it describes) and `known_date` (the first date it could have
   been known). Agents and the backtest only read rows where
   `known_date <= t`.
4. **Neutral fallback.** If a factor has no valid data for a stock on date
   t, its 0–100 score is 50 and the row is flagged `imputed=true`. Never drop
   a stock silently.
5. Secrets come only from `.env` (never committed).
6. Work in phases (Section 12). Stop after each phase, summarize what was
   built, show test results, and wait for the go-ahead.
7. Typed, pure functions where possible; docstrings; `ruff` + `black`;
   `pytest` for everything; no notebooks in `src/`.
8. FactSet data is licensed for internal use only. Never write FactSet data
   into anything public or into a shared dashboard export.

---

## 1. Tech stack

- Python 3.11+, pandas, numpy, pandas-ta (or TA-Lib), duckdb (+ parquet),
  requests, tenacity (retries), pydantic (config), python-dotenv,
  pandas_market_calendars, APScheduler, FastAPI, Streamlit, matplotlib/plotly,
  pytest.
- FactSet official Python SDKs (`fds.sdk.*` packages, e.g.
  `fds.sdk.FactSetFundamentals`, `fds.sdk.FactSetEstimates`,
  `fds.sdk.FactSetPrices`, `fds.sdk.FactSetOwnership`, `fds.sdk.Symbology`,
  `fds.sdk.Formula`, `fds.sdk.EventsandTranscripts`) with `fds.sdk.utils` for
  authentication. Confirm exact package names on developer.factset.com before
  installing.
- Alpaca paper-trading API (`alpaca-py`) for order execution.

---

## 2. Repository layout

```
stock-agents/
  .env.example
  config/
    settings.yaml
    weights.yaml
    universe_seed.csv
    factset_metrics.yaml        # populated in Phase 1
  src/stock_agents/
    sources/
      eodhd.py
      factset.py
      fred.py
      finra.py
      social.py
      alpaca_broker.py
    ingest/
      symbology.py
      universe.py
      prices.py
      fundamentals.py
      estimates.py
      news_sentiment.py
      ownership.py
      short_interest.py
      events.py
      macro.py
    quality/validate.py
    pit.py
    factors/
      technical.py
      sentiment.py
      momentum.py
      fundamental.py
    agents/
      base.py
      technical.py
      sentiment.py
      momentum.py
      fundamental.py
    engine/
      scoring.py
      combiner.py
      portfolio.py
      backtest.py
      metrics.py
    jobs/
      daily_data.py
      daily_signals.py
      execute_orders.py
      mark_to_market.py
      weekly_fundamentals.py
      backfill.py
    api/main.py
    ui/app.py
  scripts/probe_*.py
  tests/   (unit + fixtures)
  docs/DATA_NOTES.md, docs/RUNBOOK.md
```

---

## 3. Data sources (full matrix)

See the pasted build prompt in session history for the detailed source-of-truth
matrix, point-in-time rules per dataset, and the DuckDB table list. Highlights:

- **Prices (primary)**: EODHD `eod/{SYM}.US` and `eod-bulk-last-day/US`.
- **Prices (cross-check)**: FactSet Prices API.
- **Fundamentals (primary)**: FactSet Fundamentals API, point-in-time via
  filing dates. **Fallback**: EODHD fundamentals quarterly with `filing_date`
  as `known_date`.
- **Estimates / ratings / surprises / events**: FactSet Estimates + Events &
  Transcripts.
- **News**: EODHD `news?s={SYM}.US` + aggregated `sentiments`.
- **Ownership + insider**: FactSet Ownership (fallback SEC EDGAR Form 4).
- **Short interest**: FINRA consolidated short-interest files (free, twice
  monthly), `known_date = FINRA publication date`.
- **Macro**: FRED `DGS3MO`, `VIXCLS`.
- **Execution**: Alpaca paper (`alpaca-py`).

Internal key is `ticker` (e.g. `BRK-B`). EODHD symbol is `{ticker}.US`. FactSet
uses its own IDs; always resolve through `symbology`, never string-hack.

Core DuckDB tables:
`symbology`, `index_membership`, `classification`, `prices_daily`,
`corporate_actions`, `fundamentals_pit`, `estimates_pit`, `analyst_pit`,
`earnings_surprise`, `events_calendar`, `news`, `sentiment_daily`,
`insider_tx`, `short_interest`, `social_daily`, `macro`, `factor_values`,
`agent_scores`, `signals`, `target_weights`, `orders`, `fills`, `positions`,
`nav`, `quality_log`, `run_log`. All writes are idempotent upserts.

---

## 4. Data quality (`quality/validate.py`)

Run after every ingest. Blocking failures stop the signal job.

| Check | Blocking |
| --- | --- |
| ≥ 98% of universe has today's price row | Yes |
| No negative/zero prices; volume > 0 | Yes |
| \|daily adj return\| > 25% with no corporate action | Yes (review) |
| EODHD vs FactSet close differ > 0.5% | No (log) |
| Duplicate (date, ticker) rows | Yes |
| Stale price (same close 3+ days with volume) | No |
| Fundamentals metric jumps > 10x QoQ | No (winsorize) |
| News returned 0 items for > 50% of universe | No (flag outage) |
| Any non-price source failed after retries | No |

Use adjusted close for returns; scale OHL by `adj_close / close`.

---

## 5. Scoring engine, agents, combiner, portfolio, backtest

See Sections 5–11 of the pasted prompt in session history. Weights are in
`config/weights.yaml` with named presets. Point-in-time helpers live in
`src/stock_agents/pit.py`; agents may only read data through them.

---

## 12. Phased plan

| Phase | Build | Done when |
| --- | --- | --- |
| 0 | Repo skeleton, config, `.env.example`, DB schema, logging, CI tests | `pytest` passes; `make lint` clean |
| 1 | Probe scripts; fixtures; `DATA_NOTES.md`; `factset_metrics.yaml` | Reviewed and entitlements confirmed |
| 2 | Symbology + universe + prices + corporate actions + validation; backfill from 2015 | 100% price coverage; EODHD vs FactSet cross-check report |
| 3 | Fundamentals PIT, estimates, ratings, surprises, events, insider, short, news, macro ingest | Coverage report by dataset/year; PIT tests (no `known_date > t`) |
| 4 | Scoring engine + Technical + Momentum agents | Indicators match pandas-ta; reproducible rankings |
| 5 | Fundamental + Sentiment agents | Coverage/imputation report; sector-neutral test |
| 6 | Combiner + portfolio + backtest + metrics | Single-agent and combined BTs 2016→today; walk-forward report |
| 7 | Daily jobs + scheduler + Alpaca paper + alerts | 3 days unattended with correct signals + NAV |
| 8 | FastAPI + Streamlit UI | All controls persist presets; UI mirrors the HTML demo |

Start with Phase 0. At the end of each phase, list what was built, what
couldn't be verified (and why), and what is needed from me.
