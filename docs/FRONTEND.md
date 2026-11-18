# Phase 4 Next.js frontend

## 1. Start the API and frontend

Keep FastAPI running on port 8701. Follow the [jobs runbook](JOBS.md) to
start Redis, RQ, the scheduler and object storage. From the repository root,
set up the web app with Node.js 24 and pnpm.

```powershell
Set-Location apps/web
pnpm install --frozen-lockfile
pnpm gen:api
pnpm dev --hostname 127.0.0.1 --port 3001
```

The current Windows preview uses port 3001 because another service is on
3000. The FastAPI HTML app remains available on 8701 during rollout.

## 2. Verify the production build

```powershell
pnpm lint
pnpm typecheck
pnpm build
pnpm start --hostname 127.0.0.1 --port 3001
```

Set `API_ORIGIN` to the server-side address for FastAPI. The browser uses
the same-origin `/backend` proxy for API calls. The proxy forwards the
HttpOnly session cookie and leaves authorization to FastAPI. Authenticated
responses use `private, no-store`. The existing RQ dashboard is also
available through Next.js at `/_admin/rq/`. Use a browser-reachable
`S3_PUBLIC_ENDPOINT` on FastAPI for signed artifact links.

For IP-based production login limits, configure the deployment edge to
overwrite a dedicated forwarding header with the verified client address.
Set `TRUSTED_CLIENT_IP_HEADER` on Next.js to that header, restrict direct
access to the origin, and configure Uvicorn to accept forwarded addresses
from the Next.js gateway. Local development uses the loopback address.

## 3. Select the sign-in provider

Self-hosted JWT uses the existing FastAPI accounts, login and administrator
bootstrap. For Clerk, set `NEXT_PUBLIC_AUTH_PROVIDER=clerk`,
`NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` and `CLERK_SECRET_KEY` before building.
Match FastAPI's Clerk tenant and authorized origins to the frontend and
set `CLERK_JWT_TEMPLATE` if the API expects a custom audience. Provision
roles in FastAPI using the [authentication runbook](AUTHENTICATION.md).

Price charts use TradingView Lightweight Charts, copyright 2023 TradingView,
Inc., under the Apache 2.0 license. [TradingView](https://www.tradingview.com/)
