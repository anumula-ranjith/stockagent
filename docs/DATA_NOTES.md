# Data notes

Living document. Every confirmed endpoint, field name and entitlement
decision from Phase 1 probes goes here. If the spec and this file disagree,
this file wins (it is backed by live API responses).

## Nifty ranking inputs

The NSE archive publishes the current membership. The November 18, 2026 file
contained 500 tradable stocks and the inactive DUMMYHEG placeholder. The daily
exchange job records when it first observed each membership. [NSE constituent file](https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv)

| Local observations on November 18, 2026 | Tradable Nifty members covered |
| --- | ---: |
| Closing prices | 500 (496 EODHD, 4 NSE final Bhavcopy) |
| EODHD fundamental snapshots | 497 |
| FactSet Formula fundamental snapshots | 500 |
| Current FY1 or FY2 EPS estimates from FactSet | 463 |
| One-month change in FactSet consensus rating | 447 |
| EODHD headlines in the seven calendar days ending November 18 | 28 |
| At least three EODHD headlines in that window | 1 |

EODHD's NSE symbol directory and fundamentals feed omitted BAGMANE, CMPDI,
and HEGAM. The seven-day news window contained 36 mentions. Social activity,
insider transactions, and short interest had no local observations. Country
coverage and analyst participation vary by instrument. Ownership percentages
measure holdings and cannot establish insider trades. [EODHD fundamentals](https://eodhd.com/financial-apis/stock-etfs-fundamental-data-feeds) · [EODHD news and sentiment](https://eodhd.com/financial-apis/stock-market-financial-news-api)

The local FactSet account returned HTTP 403 on the dedicated Fundamentals and
Estimates catalog routes. Formula cross-sectional POST requests using official
ISINs returned financial ratios, EPS consensus and analyst ratings. Formula
columns use provider-returned request IDs. When an EODHD ISIN differs from
the exchange file after a corporate action, the loader checks whether both
resolve to one FactSet regional security ID. [FactSet Formula API](https://developer.factset.com/api-catalog/formula-api)

Snapshots use the day observed in India for their known date. Financial ratios
and yields use fractions, market caps use INR, and earnings-surprise values use
percentage points. A positive analyst-rating change means the consensus
improved over one month. Fiscal-year free cash flow yield and trailing free
cash flow yield are separate fields. Buyback yield uses annual cash repurchases
less cash proceeds from stock issuance, divided by current market cap.

The native scheduler and Windows EOD task check for a completed exchange
refresh before updating provider snapshots. To resume today's load manually,
run `python -m stock_agents.ingest.provider_inputs --due` in the project
environment. PostgreSQL stores per-provider, per-date progress in `run_log`.
Completed members skip subsequent requests that day. EODHD loads check the
remaining daily call allowance before requesting fundamentals. Each provider
can finish while the other is unavailable.

## How to populate this file

1. Put every credential into `.env` (see `.env.example`).
2. Install the FactSet SDKs you are entitled to:
   ```
   pip install fds.sdk.utils \
               fds.sdk.Symbology \
               fds.sdk.FactSetFundamentals \
               fds.sdk.FactSetEstimates \
               fds.sdk.FactSetPrices \
               fds.sdk.FactSetOwnership \
               fds.sdk.EventsandTranscripts
   ```
3. Run the probes:
   ```
   python scripts/run_all_probes.py
   ```
4. Fill in the status table below from the run summary, and paste any
   surprise into "Deviations from the spec".
5. Edit `config/factset_metrics.yaml`, replacing every `TBD` with the metric
   code you confirmed under `fundamentals/metrics` (listed in the saved
   `tests/fixtures/factset_fundamentals_metrics.json.gz`).

## Status by source

| Source                            | Endpoint(s) probed | Entitled | Fixture path                                     | Notes          |
| --------------------------------- | ------------------ | -------- | ------------------------------------------------ | -------------- |
| EODHD                             | eod, bulk-eod, splits, div, fundamentals, news, sentiments, calendar/earnings | Yes for the Nifty feeds described above | tests/fixtures/eodhd_*.json.gz | Live coverage depends on instrument |
| FactSet Formula                   | POST /formula-api/v1/cross-sectional | Yes | Private PostgreSQL observations | NSE ISINs, INR-denominated listings |
| FactSet Symbology                 | translate_by_symbols | ?        | tests/fixtures/factset_symbology_*.json.gz    | phase 1        |
| FactSet Fundamentals              | /content/factset-fundamentals/v2/metrics | HTTP 403 | — | Financial statement metrics available through Formula |
| FactSet Estimates                 | /content/factset-estimates/v2/metrics | HTTP 403 | — | Consensus estimates and ratings available through Formula |
| FactSet Prices                    | get_prices        | ?        | tests/fixtures/factset_prices_*.json.gz        | cross-check    |
| FactSet Ownership                 | insider_tx, holdings | ?        | tests/fixtures/factset_ownership_*.json.gz    | phase 1        |
| FactSet Events & Transcripts      | events (earnings) | ?        | tests/fixtures/factset_events_*.json.gz        | phase 1        |
| FRED                              | series/DGS3MO, series/VIXCLS | ?        | tests/fixtures/fred_series_*.json.gz          | phase 1        |
| FINRA short interest              | daily reg-sho + static files | n/a      | tests/fixtures/finra_*.json.gz                | needs schedule |
| Alpaca paper                      | account, clock, positions, orders | ?        | tests/fixtures/alpaca_*.json.gz               | phase 7        |

## Deviations from the spec

_(record any field-name or endpoint surprise here, with date and author)_
