# Runbook

Day-to-day operations. Expanded as phases land.

See [PostgreSQL cutover](MIGRATIONS.md) for the operational warehouse and
local Compose setup. See [Authentication](AUTHENTICATION.md) for account
bootstrap and deployment. See [Jobs and scheduler](JOBS.md) for operating RQ.
See [Next.js frontend](FRONTEND.md) for the web app and its API gateway.
See [Observability and CI](OBSERVABILITY.md) for health checks, traces, metrics, and CI.
The API, CLI, scheduled ingestion, scoring and backtests use PostgreSQL.
Set `DATABASE_URL` in `.env` before running these commands.

## First-time setup

```
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
pip install -e .
cp .env.example .env     # fill in keys
make test
```

## Initialize the warehouse

```
python -m stock_agents.cli init-db
```

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
