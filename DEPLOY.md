# Run Stock Agents locally

Open [the web app](http://localhost:3001). FastAPI listens on [127.0.0.1:8701](http://127.0.0.1:8701/docs). PostgreSQL stores prices and accounts, Redis queues jobs, and SeaweedFS serves private backtest downloads.

## Install once on Windows

Use Python 3.12, Node.js 24, the pnpm version in `apps/web/package.json`, PostgreSQL 16, Redis and the SeaweedFS `weed` executable. Redis can run natively or in WSL on localhost. SeaweedFS provides a [Windows release](https://github.com/seaweedfs/seaweedfs/releases/tag/4.54).

From the repository root in PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-prod.txt
python -m pip install --no-deps -e .
pnpm --dir apps/web install --frozen-lockfile
if (!(Test-Path .env)) { Copy-Item .env.example .env }
```

Keep the current `.env` and persistent service directories on an existing installation. For a new installation, start PostgreSQL and create an owning role and a database. With PostgreSQL's `bin` directory on PATH:

```powershell
createuser -h 127.0.0.1 -U postgres --pwprompt stockagents
createdb -h 127.0.0.1 -U postgres -O stockagents stockagents
```

Set `DATABASE_URL` to the role, password, host, port and database in `.env`. The example uses port 5432. The existing workstation uses **55433**. Percent-encode reserved URL characters in passwords. TimescaleDB is optional. [Database migrations](docs/MIGRATIONS.md)

| Root `.env` settings | Local values |
| --- | --- |
| `REDIS_URL` | `redis://127.0.0.1:6379/0` |
| `S3_ENDPOINT`, `S3_PUBLIC_ENDPOINT` | `http://127.0.0.1:9002` |
| `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` | Choose a bucket, an access key and a random secret. The object store launcher reads these settings. |
| `JWT_SECRET`, `BOOTSTRAP_SIGNUP_TOKEN` | Generate two independent values by running `python -c "import secrets; print(secrets.token_hex(32))"` twice. |
| `AUTH_PROVIDER`, `AUTH_COOKIE_SECURE`, `FRONTEND_URL` | `jwt`, `false`, `http://localhost:3001` for the local HTTP app. |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL`, `EMAIL_PASSWORD` | SMTP settings for public email verification and recovery. |
| `SCHEDULER_RUN_MARKET_JOBS` | Set `false` for queue reconciliation alone. The default enables scheduled ingestion and scoring. |

## Start or restart a service

Use the project root and activated virtual environment in each terminal. Start only missing services. Run one scheduler.

1. Start the existing PostgreSQL instance and Redis service. If running a native Redis binary manually, reuse its existing data directory. For a **fresh** Redis installation:

   ```powershell
   $redisData = New-Item -ItemType Directory -Force "$env:LOCALAPPDATA\StockAgents\redis"
   redis-server --bind 127.0.0.1 --port 6379 --protected-mode yes --appendonly yes --dir $redisData.FullName
   ```

2. Start the artifact store with its existing data directory on each restart. For a **fresh** store:

   ```powershell
   python -m scripts.local object-store --data-dir "$env:LOCALAPPDATA\StockAgents\artifacts"
   ```

   Add `--executable "C:\path\to\weed.exe"` if the binary is outside PATH.

3. On first setup or after pulling schema changes, initialize the database, apply outstanding Alembic revisions and ensure the private bucket exists:

   ```powershell
   python -m scripts.local prepare
   ```

4. Run each long-running service in its own terminal:

   | Service | Command |
   | --- | --- |
   | FastAPI | `python -m scripts.local api` |
   | RQ worker | `python -m scripts.local worker` |
   | APScheduler | `python -m scripts.local scheduler` |
   | Next.js dev server | `python -m scripts.local web-dev` |
   | Next.js production server (alternative web command) | `pnpm --dir apps/web build`, then `python -m scripts.local web` |

   To restart a foreground service, press Ctrl+C in its terminal, wait for exit and repeat its command. Rebuild the production frontend after changing web code.

### Existing Windows workstation

This workstation's PostgreSQL cluster, Redis persistence and SeaweedFS objects live in previous project installations under the Windows temporary directory. Keep those directories and back them up before any temporary-file cleanup. To bring these same services back after a reboot, activate the project virtual environment and use the following commands only for services that are stopped. Run Redis and SeaweedFS in separate terminals.

```powershell
$pgInstall = Join-Path $env:TEMP 'stock-agents-phase1-timescale'
& "$pgInstall/postgres/bin/pg_ctl.exe" -D "$pgInstall/data" -l "$pgInstall/server.log" -o '-p 55433 -h 127.0.0.1' start

$redisInstall = Join-Path $env:TEMP 'stock-agents-phase3-redis'
& "$redisInstall/Redis-8.10.3-Windows-x64-msys2/redis-server.exe" --bind 127.0.0.1 --port 6379 --protected-mode yes --appendonly yes --dir "$redisInstall/data"

$storeInstall = Join-Path $env:TEMP 'stock-agents-phase3-object-store'
python -m scripts.local object-store --executable "$storeInstall/weed.exe" --data-dir "$storeInstall/data"
```

## Verify and use the app

```powershell
Invoke-RestMethod http://127.0.0.1:8701/health
Invoke-RestMethod http://localhost:3001/backend/health
```

Both checks should report `ok` for PostgreSQL, Redis and S3. Append `?include_stats=true` for warehouse counts.

- Bootstrap the first administrator on the [API sign-in page](http://127.0.0.1:8701/login) using the bootstrap token. Sign in to the [web app](http://localhost:3001/login) with those credentials. Public accounts use [email signup](http://localhost:3001/signup). [Authentication](docs/AUTHENTICATION.md)
- Submit a date range with stored prices from [Backtest](http://localhost:3001/backtest) as an administrator. The page polls the job, displays the completed report and provides a private JSON download.
- Open [Job queues](http://localhost:3001/_admin/rq/) in the same signed-in browser to see active workers, queued jobs and failures. [Jobs and schedule](docs/JOBS.md)

## Screen the Nifty 500

1. Sign in and open the [screener](http://localhost:3001/screener). The latest session, constituent count, adjusted-price coverage and 52-week coverage appear above the results.
2. For stocks within 10% of their yearly high, enter `10` under **Within % below high** and select **Run screen**. Use **Within % above low** to measure distance from the yearly low.
3. For a bullish EMA crossover yesterday, choose periods `9` and `21`, select **Crossed above**, and set **Trading sessions ago** to `1`. Clear the range field first to search the whole index. With multiple conditions enabled, every condition must match.
4. For MACD, set the fast, slow and signal periods and choose a line relationship or crossover. Each indicator has its own session selector. Click a ticker for its price chart and stock detail.

The screener uses positive-volume NSE sessions from the local warehouse. The range uses adjusted intraday highs and lows over 52 calendar weeks and requires coverage of at least 95% of observed sessions. EMA and MACD use adjusted closes. Values in rupees use the latest closing-price units.

## Tune the research dashboard

Open the [four-agent dashboard](http://localhost:3001/dashboard). Select an agent, adjust its weights and inspect the long and short candidates. **Combined** controls portfolio selection. **Portfolio & Backtest** replays those settings through the local worker. The current-cohort option uses end-date constituents and revised prices. Historical membership mode requires observations recorded by each signal date.

The scheduler refreshes the official NSE membership and local prices, then checks for due provider snapshots. To run a provider snapshot manually after an EOD load, run `python -m stock_agents.ingest.provider_inputs` in the project environment. Credentials belong in the local `.env`. EODHD and FactSet can return different coverage for the same security.

## Development checks

```powershell
python -m pip install -r requirements-dev.txt
python -m ruff check src scripts tests
python -m mypy
python -m pytest
pnpm --dir apps/web lint
pnpm --dir apps/web build
pnpm --dir apps/web typecheck
```

For database integration tests, first set `TEST_DATABASE_URL` to a local PostgreSQL role with `CREATEDB` permission. The suite creates and removes uniquely named test databases. Without this setting, pytest reports those cases as skipped. CI also runs a native end-to-end smoke test against an isolated database.
