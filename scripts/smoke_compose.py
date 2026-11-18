"""Exercise the isolated Docker Compose stack from the CI runner."""

import json
import os
from http.cookiejar import CookieJar
from time import monotonic, sleep
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

BASE = "http://127.0.0.1:8701"
DAY = "2025-01-03"


def main() -> None:
    client = build_opener(HTTPCookieProcessor(CookieJar()))
    credentials = {"email": "compose-smoke@example.com", "password": "isolated CI account password"}
    body = json.dumps(credentials).encode()
    headers = {"Content-Type": "application/json", "X-Stock-Agents-Request": "1"}
    bootstrap = {**headers, "X-Bootstrap-Signup-Token": os.environ["SMOKE_BOOTSTRAP_TOKEN"]}
    with client.open(Request(f"{BASE}/signup", data=body, headers=bootstrap), timeout=10) as response:
        assert response.status == 201 and json.load(response)["is_admin"]
    with client.open(Request(f"{BASE}/login", data=body, headers=headers), timeout=10) as response:
        assert response.status == 200
    with client.open(f"{BASE}/me", timeout=10) as response:
        assert json.load(response)["is_admin"]
    with client.open(f"{BASE}/_admin/rq/", timeout=10) as response:
        assert response.status == 200

    path = f"/backtest/run?start={DAY}&end={DAY}&n=3"
    headers["X-Request-ID"] = "compose-smoke-backtest"
    with client.open(Request(BASE + path, data=b"", headers=headers), timeout=10) as response:
        assert response.status == 202 and response.headers["X-Request-ID"] == headers["X-Request-ID"]
        job_id = json.load(response)["job_id"]
    deadline = monotonic() + 60
    while monotonic() < deadline:
        with client.open(f"{BASE}/jobs/{job_id}", timeout=10) as response:
            job = json.load(response)
        if job["status"] == "finished":
            break
        if job["status"] == "failed":
            raise RuntimeError("The Compose backtest failed")
        sleep(1)
    else:
        raise TimeoutError("The Compose backtest did not finish within 60 seconds")

    with urlopen(job["result_url"], timeout=10) as response:
        assert json.load(response)["n_days"] == 1
    with urlopen(f"{BASE}/metrics", timeout=10) as response:
        assert b'stock_agents_jobs_completed_total{job_type="backtest",outcome="success"} 1.0' in response.read()
    print("Compose sign-in, admin dashboard, backtest, signed artifact, and metrics passed.")


if __name__ == "__main__":
    main()
