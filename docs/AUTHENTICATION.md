# Phase 2 authentication

## 1. Apply the database revision

Run `python -m alembic upgrade head` against the existing PostgreSQL database.
Compose runs this on API startup. Use `python -m alembic check` to check schema
drift and keep the DuckDB research warehouse mounted at the configured path.

## 2. Create the first administrator

Set `AUTH_PROVIDER=jwt` and generate separate random values for `JWT_SECRET`
and `BOOTSTRAP_SIGNUP_TOKEN` in `.env` for local development or the host's
secret manager for deployment. Each value needs at least 32 bytes. Use
HTTPS for production so the browser can send its Secure session cookie.
The local HTTP launcher can set `AUTH_COOKIE_SECURE=false` on loopback.

Open [Sign in](http://127.0.0.1:8701/login), expand **Set up the first
administrator**, and enter your email, password and bootstrap token.
The API equivalent is `POST /signup` with the token in the
`X-Bootstrap-Signup-Token` request header. PostgreSQL serializes concurrent
bootstrap attempts and records consumption in the audit log. Remove the
bootstrap secret from configuration after use.

## 3. Sign in and run a backtest

`POST /login` accepts a JSON email and password. Browser sessions use an
HttpOnly, SameSite cookie. API clients can send the returned token in
`Authorization: Bearer <token>`. Both expire after one hour. Cookie-based
writes use the `X-Stock-Agents-Request: 1` header. `GET /me` returns the
role stored in PostgreSQL.

Signed-in users can view rankings and backtest reports. Administrators can
create additional accounts with `POST /signup` and submit backtests,
ingestion and score recomputation. An accepted backtest returns HTTP 202
and a job ID. The dashboard polls `GET /jobs/{job_id}`, which checks job
ownership or administrator access. The [jobs runbook](JOBS.md) covers the
RQ worker, scheduler and private artifact downloads.

Audit rows record the actor, action, client IP, timestamp and a SHA-256
hash of the normalized action parameters. For production replicas, point
`AUTH_RATE_LIMIT_STORAGE_URL` at shared Redis. Single-process native
development uses memory storage by default. Sign-in is limited to five
attempts per minute per client IP and backtest submission to three per
hour per administrator. Configure Uvicorn to trust forwarded addresses
only from your reverse proxy.

## 4. Optional Clerk authentication

Set `AUTH_PROVIDER=clerk`, `CLERK_ISSUER`, `CLERK_JWKS_URL`, and
`CLERK_AUTHORIZED_PARTIES` with your Clerk issuer, HTTPS JWKS endpoint and
comma-separated frontend origins. Set `CLERK_AUDIENCE` if your tokens
include an application audience. A first-admin bootstrap or an existing
administrator can provision an account with `email` and `clerk_subject`
through `POST /signup`. Use the Clerk user ID as the subject. Clerk clients
send a session token as a bearer credential. The current HTML sign-in form
uses self-hosted JWT. [Clerk token verification](https://clerk.com/docs/guides/sessions/manual-jwt-verification)
