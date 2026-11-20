# Authentication

## Public accounts and password recovery

The Next.js app exposes `/signup`, `/login`, `/verify-email`, `/forgot-password`,
`/reset-password`, and `/account`. Public registration creates a regular user.
Email verification is required before signing in. The existing `/signup` API
continues to support administrator provisioning and the first-admin bootstrap.
The public signup form calls `POST /register`.

Configure `EMAIL_HOST`, `EMAIL_PORT` (587 for STARTTLS or 465 for TLS), `EMAIL`,
and `EMAIL_PASSWORD` in `.env`. Gmail requires an app password. Configure
`FRONTEND_URL` as the trusted browser origin used in account emails, such as
`http://localhost:3001` locally or your HTTPS frontend origin in production.
Restart the API after changing these settings.

Verification links expire after one hour and reset links after 30 minutes.
Each link is single-use. The database stores token hashes. Links place the
token in a URL fragment that the browser consumes without sending it in the
page request. Users explicitly submit verification or a new password.
Password changes revoke previous sessions on every device.

Account email requests have IP limits and a 60-second per-account resend
cooldown. Signup and recovery responses avoid disclosing existing accounts.
SMTP delivery errors return a retryable message and roll back the pending
registration or token replacement. Existing accounts remain verified when
the migration is applied.

## 1. Apply the database revision

Run `python -m alembic upgrade head` against the existing PostgreSQL database.
The local prepare command also applies pending revisions. Use
`python -m alembic check` to check schema drift.

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
