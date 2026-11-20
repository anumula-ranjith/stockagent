from datetime import UTC, date, datetime, timedelta
from time import monotonic, sleep
from types import SimpleNamespace

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import select

from stock_agents.api import auth_clerk, diagnostics
from stock_agents.api.auth import limiter
from stock_agents.api.main import app
from stock_agents.jobs.worker import WindowsWorker
from stock_agents.storage.postgres import AuditLog, User
from stock_agents.storage.warehouse import connect

ADMIN_EMAIL = "admin@example.com"
VIEWER_EMAIL = "viewer@example.com"
PASSWORD = "test password for sign in"
BOOTSTRAP = "test-bootstrap-token-for-the-first-admin-only"
DUMMY_SECRET = "test-signing-key-for-stock-agents-authentication"


def test_backtest_requires_authentication():
    with TestClient(app) as client:
        result = client.post("/backtest/run?start=2025-01-01&end=2025-01-02&n=3")
        assert result.status_code == 401
        assert result.headers["www-authenticate"] == "Bearer"


def test_login_form():
    with TestClient(app) as client:
        result = client.get("/login")
        assert result.status_code == 200
        assert 'autocomplete="current-password"' in result.text
        assert result.headers["cache-control"] == "private, no-store"
        assert "script-src 'nonce-" in result.headers["content-security-policy"]


def test_production_market_data_requires_authentication(monkeypatch):
    monkeypatch.setenv("REQUIRE_MARKET_DATA_AUTH", "true")
    with TestClient(app) as client:
        for path in ("/universe", "/prices/SAMPLE", "/news/SAMPLE", "/sentiment/SAMPLE"):
            assert client.get(path).status_code == 401


def test_admin_bootstrap_login_audit_and_backtest(
    auth_database, rq_test_queue, _isolated_paths, monkeypatch
):
    monkeypatch.setenv("AUTH_PROVIDER", "jwt")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    monkeypatch.setenv("JWT_SECRET", DUMMY_SECRET)
    monkeypatch.setenv("BOOTSTRAP_SIGNUP_TOKEN", BOOTSTRAP)
    limiter.reset()
    now = date.today()
    with connect() as conn:
        conn.execute(
            """INSERT INTO prices_daily (ticker, date, adj_close, source, known_date)
               VALUES ('SAMPLE', ?, 11.0, 'eodhd', ?)""",
            [now, now],
        )
    route = f"/backtest/run?start={now}&end={now}&n=3"
    with TestClient(app) as client:
        assert client.get("/dashboard").status_code == 200
        assert client.get("/combine").status_code == 401
        assert client.get("/backtest/latest").status_code == 401
        assert client.post(route).status_code == 401
        admin_fields = {"email": ADMIN_EMAIL, "password": PASSWORD}
        header = {"X-Bootstrap-Signup-Token": BOOTSTRAP}
        assert client.post("/signup", json=admin_fields).status_code == 401
        admin = client.post("/signup", headers=header, json=admin_fields)
        assert admin.status_code == 201, admin.text
        assert admin.json()["is_admin"] is True
        assert client.post("/signup", headers=header, json=admin_fields).status_code == 403

        bad_login = client.post("/login", json={"email": ADMIN_EMAIL, "password": "wrong"})
        assert bad_login.status_code == 401
        admin_login = client.post("/login", json=admin_fields)
        assert admin_login.status_code == 200, admin_login.text
        assert "HttpOnly" in admin_login.headers["set-cookie"]
        assert "SameSite=strict" in admin_login.headers["set-cookie"]
        assert client.get("/me").json() == admin.json()
        assert client.post(route).status_code == 403  # cookie request needs the CSRF header
        admin_bearer = {"Authorization": "Bearer " + admin_login.json()["access_token"]}
        first = client.post(
            route, headers={"X-Stock-Agents-Request": "1", "X-Request-ID": "backtest-trace-check"}
        )
        assert first.status_code == 202, first.text
        queued = rq_test_queue.fetch_job(first.json()["job_id"])
        assert queued.meta["request_id"] == "backtest-trace-check"
        assert queued.meta["trace_context"]["traceparent"].startswith("00-")

        viewer_fields = {"email": VIEWER_EMAIL, "password": PASSWORD}
        viewer = client.post("/signup", headers=admin_bearer, json=viewer_fields)
        assert viewer.status_code == 201, viewer.text
        viewer_login = client.post("/login", json=viewer_fields)
        viewer_bearer = {"Authorization": "Bearer " + viewer_login.json()["access_token"]}
        assert client.get("/me", headers=viewer_bearer).json()["is_admin"] is False
        for path in (route, "/admin/ingest", "/admin/recompute"):
            assert client.post(path, headers=viewer_bearer).status_code == 403

        job_url = f"/jobs/{first.json()['job_id']}"
        assert client.get(job_url, headers=viewer_bearer).status_code == 404
        assert client.get("/_admin/rq/", headers=viewer_bearer).status_code == 403
        assert client.get("/_admin/rq/", headers=admin_bearer).status_code == 200
        asset = "/_admin/rq/static/js/jquery-3.5.1.min.js"
        assert client.get(asset, headers=viewer_bearer).status_code == 403
        assert client.get(asset, headers=admin_bearer).status_code == 200
        WindowsWorker(
            [rq_test_queue],
            connection=rq_test_queue.connection,
            serializer=rq_test_queue.serializer,
        ).work(burst=True)
        deadline = monotonic() + 10
        while monotonic() < deadline:
            result = client.get(job_url, headers=admin_bearer).json()
            if result["status"] != "queued":
                break
            sleep(0.2)
        assert result["status"] == "finished", result
        assert result["result"]["n_days"] == 1
        assert result["result_key"] == "backtests/" + result["job_id"]
        assert result["result_url"] == "https://objects.example.com/" + result["result_key"]
        assert client.get("/backtest/latest", headers=viewer_bearer).json() == result["result"]
        assert client.get("/health/deep", headers=viewer_bearer).status_code == 403

        async def dependencies_ready():
            return {"status": "ok", "checks": {"postgres": "ok", "redis": "ok", "s3": "ok"}}

        async def provider_ready():
            return "ok"

        monkeypatch.setattr(diagnostics, "readiness", dependencies_ready)
        monkeypatch.setattr(diagnostics, "eodhd_check", provider_ready)
        monkeypatch.setattr(diagnostics, "factset_check", provider_ready)
        deep_health = client.get("/health/deep", headers=admin_bearer)
        assert deep_health.status_code == 200
        assert deep_health.json()["checks"] == dict.fromkeys(
            ["postgres", "redis", "s3", "eodhd", "factset"], "ok"
        )

        metrics = client.get("/metrics").text
        assert 'stock_agents_jobs_completed_total{job_type="backtest",outcome="success"} 1.0' in metrics

        assert client.post(route, headers=admin_bearer).status_code == 202
        assert client.post(route, headers=admin_bearer).status_code == 202
        assert client.post(route, headers=admin_bearer).status_code == 429
        for _ in range(2):
            assert client.post("/login", json=admin_fields).status_code == 200
        assert client.post("/login", json=admin_fields).status_code == 429
        assert client.post("/logout", headers={"X-Stock-Agents-Request": "1"}).status_code == 204
        assert client.get("/me").status_code == 401

    with auth_database.connect() as conn:
        rows = conn.execute(select(AuditLog.__table__)).all()
        assert [r.action for r in rows].count("/backtest/run") == 3
        assert [r.action for r in rows].count("bootstrap_signup") == 1
        assert [r.action for r in rows].count("signup") == 1
        assert all(len(r.request_hash) == 64 and r.ip for r in rows)
        hashes = conn.execute(select(User.__table__.c.hashed_pwd)).scalars().all()
        assert all(value.startswith("$argon2id$") for value in hashes)


def test_clerk_verifies_identity_and_uses_local_roles(auth_database, monkeypatch):
    issuer = "https://clerk.example.com"
    origin = "https://app.example.com"
    subject = "user_example"
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setenv("AUTH_PROVIDER", "clerk")
    monkeypatch.setenv("CLERK_ISSUER", issuer)
    monkeypatch.setenv("CLERK_JWKS_URL", f"{issuer}/.well-known/jwks.json")
    monkeypatch.setenv("CLERK_AUTHORIZED_PARTIES", origin)
    monkeypatch.setattr(
        auth_clerk,
        "_jwks",
        lambda _url: SimpleNamespace(
            get_signing_key_from_jwt=lambda _token: SimpleNamespace(key=key.public_key())
        ),
    )
    with auth_database.begin() as conn:
        conn.execute(User.__table__.insert().values(email=VIEWER_EMAIL, clerk_subject=subject))

    now = datetime.now(UTC)

    def headers(**claims):
        payload = {
            "sub": subject,
            "iss": issuer,
            "azp": origin,
            "iat": now,
            "nbf": now,
            "exp": now + timedelta(minutes=5),
            "admin": True,
            **claims,
        }
        token = jwt.encode(payload, key, algorithm="RS256", headers={"kid": "test"})
        return {"Authorization": f"Bearer {token}"}

    with TestClient(app) as client:
        assert client.get("/me", headers=headers()).json()["is_admin"] is False
        assert client.post("/admin/recompute", headers=headers()).status_code == 403
        assert (
            client.get("/me", headers=headers(iss="https://other.example.com")).status_code == 401
        )
        assert (
            client.get("/me", headers=headers(azp="https://other.example.com")).status_code == 401
        )
        assert client.get("/me", headers=headers(exp=now - timedelta(seconds=1))).status_code == 401
