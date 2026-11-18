# Runbook

Day-to-day operations. Expanded as phases land.

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

_(populated in Phase 7)_
