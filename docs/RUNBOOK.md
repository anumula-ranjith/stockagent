# Local operations

Follow [Local startup](../DEPLOY.md) for installation, native service commands
and verification. PostgreSQL holds the operational warehouse for the API,
CLI, scheduled ingestion, scoring and backtests.

- [Database migrations and legacy imports](MIGRATIONS.md)
- [Authentication and account recovery](AUTHENTICATION.md)
- [RQ jobs and scheduling](JOBS.md)
- [Next.js frontend](FRONTEND.md)
- [Readiness, traces, metrics and CI](OBSERVABILITY.md)

## Phase-1 probes

Populate `.env` with every credential, then:

```
pip install fds.sdk.utils fds.sdk.Symbology \
            fds.sdk.FactSetFundamentals fds.sdk.FactSetEstimates \
            fds.sdk.FactSetPrices fds.sdk.FactSetOwnership \
            fds.sdk.EventsandTranscripts
python scripts/run_all_probes.py
```

Each probe writes one or more `tests/fixtures/*.json.gz` files and prints
a summary row. After the run, update `docs/DATA_NOTES.md` from the summary
and fill in `config/factset_metrics.yaml` from the metrics fixture.

## Daily operations

The scheduler and native scheduled task refresh Nifty 500 plus NSE stock F&O
membership and EOD prices after the market closes. See [Jobs](JOBS.md) for
scheduling and retry behavior. `python -m stock_agents.cli status` reads the
PostgreSQL warehouse counts.
