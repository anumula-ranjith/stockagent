#!/usr/bin/env bash
# Run on a fresh Ubuntu CI runner with an empty PostgreSQL database.
set -euo pipefail
work=$(mktemp -d)
children=()
cleanup() {
  status=$?
  for child in "${children[@]}"; do kill "$child" 2>/dev/null || true; done
  if (( status != 0 )); then
    for log in "$work"/{api,worker,scheduler}.log; do
      if [[ -e "$log" ]]; then tail -80 "$log"; fi
    done
  fi
}
trap cleanup EXIT

sudo apt-get update -qq
sudo apt-get install -y redis-server
sudo systemctl start redis-server
curl -fsSL --retry 3 https://github.com/seaweedfs/seaweedfs/releases/download/4.54/linux_amd64.tar.gz -o "$work/weed.tar.gz"
echo "e7424a82eee327809bfa449fda4924c9a0f42f6669a01288eebb1b79674c8196  $work/weed.tar.gz" | sha256sum --check --status
tar -xzf "$work/weed.tar.gz" -C "$work"

JWT_SECRET=$(openssl rand -hex 32)
BOOTSTRAP_SIGNUP_TOKEN=$(openssl rand -hex 32)
S3_SECRET_KEY=$(openssl rand -hex 32)
export JWT_SECRET BOOTSTRAP_SIGNUP_TOKEN S3_SECRET_KEY
export SMOKE_BOOTSTRAP_TOKEN="$BOOTSTRAP_SIGNUP_TOKEN"
python -m scripts.local object-store --executable "$work/weed" --data-dir "$work/storage" >"$work/store.log" 2>&1 &
children+=("$!")
curl --retry 30 --retry-all-errors --retry-delay 1 -fsS "$S3_ENDPOINT/healthz" -o /dev/null
python -m scripts.local prepare
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "INSERT INTO prices_daily (ticker, date, adj_close, source, known_date) VALUES ('SAMPLE', '2025-01-03', 11.0, 'eodhd', '2025-01-03')"
python -m uvicorn stock_agents.api.main:app --host 127.0.0.1 --port 8701 >"$work/api.log" 2>&1 &
children+=("$!")
python -m stock_agents.jobs.worker >"$work/worker.log" 2>&1 &
children+=("$!")
python -m scripts.schedule_daily >"$work/scheduler.log" 2>&1 &
children+=("$!")
api=http://127.0.0.1:8701
curl --retry 30 --retry-all-errors --retry-delay 1 -fsS "$api/health"
test "$(curl -s -o /dev/null -w '%{http_code}' "$api/health/deep")" = 401
python -m scripts.smoke_native
