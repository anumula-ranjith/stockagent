import type { NextRequest } from "next/server";
import { isIP } from "node:net";

const origin = new URL(process.env.API_ORIGIN || "http://127.0.0.1:8701");
const reads = /^(market-feed\/stock\/[^/]+\/(?:quote|candles|derivatives)|admin\/(?:angel-one(?:\/scheduled-runs)?|overview|runs(?:\/[0-9a-f-]+)?|schedules|quality|users|audit)|screener\/market-status|health|me|universe|combine|ranker\/(?:snapshot|latest)|backtest\/latest|(?:prices|news|news-status|scores|agents|sentiment|jobs|stock-memberships|stock-profile)\/[^/]+|portfolios(?:\/[^/]+)?|watchlists(?:\/[^/]+)?|brokers\/angel-one\/snapshot)$/;
const writes = /^(market-feed\/subscribe\/[^/]+|market-feed\/watchlist\/[0-9a-f-]+|admin\/(?:angel-one\/connect|runs(?:\/[0-9a-f-]+\/(?:retry|cancel))?|schedules\/(?:morning|evening)|users\/[0-9a-f-]+\/role)|stock-memberships\/[^/]+\/watchlists|login|logout|signup|register|verify-email|resend-verification|forgot-password|reset-password|change-password|backtest\/run|screener\/run|ranker\/(?:snapshot|backtest)|(?:ranker|screener)\/stock\/[^/]+|portfolios(?:\/[^/]+(?:\/entries(?:\/[^/]+)?)?)?|watchlists(?:\/[^/]+(?:\/items\/[^/]+)?)?|brokers\/angel-one\/(?:sync|snapshot))$/;

export async function proxy(request: NextRequest, segments: string[], operations = false) {
  if (segments.some(segment => !segment || segment === "." || segment === ".." || /[\/\\]/.test(segment))) {
    return new Response(null, { status: 404 });
  }
  const path = segments.map(encodeURIComponent).join("/");
  const read = request.method === "GET" || request.method === "HEAD";
  const usMarket = read ? /^us\/(?:market|watchlist|news|stock\/[A-Z0-9.-]{1,15}\/(?:candles|news|options))$/.test(path) : (request.method === "POST" && path === "us/subscribe") || (["PUT","DELETE"].includes(request.method) && /^us\/watchlist\/[A-Z0-9.-]{1,15}$/.test(path));
  if (!operations && !usMarket && !(read ? reads : writes).test(path)) {
    return new Response(null, { status: 404 });
  }
  if (operations && !read && request.method !== "POST") {
    return new Response(null, { status: 405 });
  }

  const browserOrigin = request.headers.get("origin");
  const host = request.headers.get("host");
  const expected = host ? `${request.nextUrl.protocol}//${host}` : request.nextUrl.origin;
  const bearer = request.headers.get("authorization");
  const bearerAuth = !!bearer && /^Bearer [\w.-]+$/i.test(bearer);
  if (!read && browserOrigin && browserOrigin !== expected) {
    return Response.json({ detail: "Browser origin verification failed" }, { status: 403 });
  }
  if (!read && !bearerAuth && request.headers.get("x-stock-agents-request") !== "1"
    && !(operations && request.headers.get("x-requested-with") === "XMLHttpRequest")) {
    return Response.json({ detail: "Browser request verification failed" }, { status: 403 });
  }

  const destination = new URL(operations ? `/_admin/rq/${path}` : `/${path}`, origin);
  destination.search = request.nextUrl.search;
  const headers = new Headers();
  for (const name of ["content-type", "x-stock-agents-request", "x-bootstrap-signup-token", "x-requested-with",
    "x-request-id", "traceparent", "tracestate"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  if (browserOrigin) headers.set("origin", destination.origin);
  const forwardedHeader = process.env.TRUSTED_CLIENT_IP_HEADER;
  const clientAddress = forwardedHeader && request.headers.get(forwardedHeader)?.trim();
  if (clientAddress && isIP(clientAddress)) headers.set("x-forwarded-for", clientAddress);

  if (process.env.NEXT_PUBLIC_AUTH_PROVIDER === "clerk") {
    const { auth } = await import("@clerk/nextjs/server");
    const session = await auth();
    const template = process.env.CLERK_JWT_TEMPLATE;
    const token = await session.getToken(template ? { template } : undefined);
    if (token) headers.set("authorization", `Bearer ${token}`);
  } else {
    const cookie = request.cookies.get("stock_agents_session");
    if (cookie) headers.set("cookie", `stock_agents_session=${cookie.value}`);
  }
  if (bearerAuth) headers.set("authorization", bearer);

  let upstream: Response;
  try {
    upstream = await fetch(destination, {
      method: request.method,
      headers,
      body: read ? undefined : await request.text(),
      cache: "no-store",
      redirect: "manual",
      signal: AbortSignal.timeout(path === "brokers/angel-one/sync" ? 45000 : 30000),
    });
  } catch {
    return Response.json({ detail: "The research API is unavailable" }, {
      status: 503, headers: { "Cache-Control": "private, no-store" },
    });
  }

  const returned = new Headers({
    "Cache-Control": "private, no-store",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": operations && upstream.headers.get("content-type")?.startsWith("text/html") ? "SAMEORIGIN" : "DENY",
  });
  for (const name of ["content-type", "www-authenticate", "retry-after", "content-disposition", "x-request-id"]) {
    const value = upstream.headers.get(name);
    if (value) returned.set(name, value);
  }
  for (const value of upstream.headers.getSetCookie()) returned.append("set-cookie", value);
  const location = upstream.headers.get("location");
  if (location && operations) {
    const redirect = new URL(location, destination);
    if (redirect.origin === destination.origin && redirect.pathname.startsWith("/_admin/rq/")) {
      returned.set("location", redirect.pathname + redirect.search);
    }
  }
  // The application uses the HttpOnly cookie. Keep the bearer token out of browser JavaScript.
  if (path === "login" && upstream.ok && !operations) {
    return Response.json({ signed_in: true }, { status: upstream.status, headers: returned });
  }
  return new Response(upstream.body, { status: upstream.status, headers: returned });
}
