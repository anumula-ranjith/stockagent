# Data notes

Living document. Every confirmed endpoint, field name and entitlement
decision from Phase 1 probes goes here. If the spec and this file disagree,
this file wins (it is backed by live API responses).

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
| EODHD                             | eod, bulk-eod, splits, div, fundamentals, news, sentiments, calendar/earnings | ?        | tests/fixtures/eodhd_*.json.gz                 | from probe     |
| FactSet Symbology                 | translate_by_symbols | ?        | tests/fixtures/factset_symbology_*.json.gz    | phase 1        |
| FactSet Fundamentals              | metrics, get_fds_fundamentals_for_list | ?        | tests/fixtures/factset_fundamentals_*.json.gz | phase 1        |
| FactSet Estimates                 | consensus, rating | ?        | tests/fixtures/factset_estimates_*.json.gz    | phase 1        |
| FactSet Prices                    | get_prices        | ?        | tests/fixtures/factset_prices_*.json.gz        | cross-check    |
| FactSet Ownership                 | insider_tx, holdings | ?        | tests/fixtures/factset_ownership_*.json.gz    | phase 1        |
| FactSet Events & Transcripts      | events (earnings) | ?        | tests/fixtures/factset_events_*.json.gz        | phase 1        |
| FRED                              | series/DGS3MO, series/VIXCLS | ?        | tests/fixtures/fred_series_*.json.gz          | phase 1        |
| FINRA short interest              | daily reg-sho + static files | n/a      | tests/fixtures/finra_*.json.gz                | needs schedule |
| Alpaca paper                      | account, clock, positions, orders | ?        | tests/fixtures/alpaca_*.json.gz               | phase 7        |

## Deviations from the spec

_(record any field-name or endpoint surprise here, with date and author)_
