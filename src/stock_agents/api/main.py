"""FastAPI app: shell-templated website + JSON endpoints.

Pages (HTML, all wrapped in templates/_shell.html):
  GET /                         Home / landing
  GET /dashboard                Four-agent dashboard
  GET /stocks                   Universe explorer
  GET /stocks/{ticker}          Per-ticker detail
  GET /backtest                 Backtest UI
  GET /methodology              Methodology page

JSON endpoints (read):
  GET /health
  GET /universe
  GET /prices/{ticker}
  GET /news/{ticker}
  GET /sentiment/{ticker}
  GET /agents/{name}
  GET /combine
  GET /backtest/latest

JSON endpoints (write — server-side work):
  POST /backtest/run?start=&end=&n=
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import UTC, date, timedelta
from html import escape
from pathlib import Path
from secrets import token_urlsafe
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.concurrency import run_in_threadpool

from stock_agents.api import (
    company_news,
    account,
    admin,
    auth,
    broker,
    diagnostics,
    job_routes,
    personal,
    ranker,
    screener,
    stock_profile,
)
from stock_agents.api.auth import AdminUser, CurrentUser
from stock_agents.api.screen_export import XLSX, ScreenEmail, ScreenExport, email_workbook, workbook
from stock_agents.api.rq_dashboard import admin_dashboard
from stock_agents.api.schemas import (
    AgentHistoryPoint,
    AgentScoreRow,
    CombineOut,
    CombineQuery,
    NewsItem,
    PriceBar,
    SentimentDay,
    UniverseRow,
)
from stock_agents.common.logging import configure
from stock_agents.common.telemetry import ObserveRequests, flush_traces, setup_tracing
from stock_agents.storage import ReadConnection, get_conn
from stock_agents.storage.postgres import dispose_engine

UI_DIR = Path(__file__).resolve().parent.parent / "ui"
TPL_DIR = UI_DIR / "templates"
STATIC_DIR = UI_DIR / "static"
SHELL = (TPL_DIR / "_shell.html").read_text(encoding="utf-8")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure(service="stock-agents.api")
    setup_tracing("stock-agents.api")
    async def warm_market():
        generation = None
        while True:
            try:
                from stock_agents.jobs.queue import _redis, redis_url
                current = await asyncio.to_thread(_redis(redis_url()).get, "quantora:market-generation")
                if current != generation:
                    ranker._inputs.invalidate()
                    screener._history.invalidate()
                    admin.quality_cache.invalidate()
                    generation = current
                await asyncio.gather(
                    asyncio.to_thread(ranker._cached_inputs, date.today(), 0),
                    asyncio.to_thread(screener.cached_history),
                )
            except Exception:
                pass  # Request handlers still report a failed cold load; retry on the next cycle.
            await asyncio.sleep(60)
    warmer = asyncio.create_task(warm_market()) if os.getenv("PRELOAD_MARKET_DATA") == "true" else None
    try:
        yield
    finally:
        if warmer:
            warmer.cancel()
            await asyncio.gather(warmer, return_exceptions=True)
        await dispose_engine()
        await run_in_threadpool(flush_traces)


app = FastAPI(title="stock-agents", version="0.3.0", lifespan=lifespan)
app.state.limiter = auth.limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.include_router(auth.router)
app.include_router(company_news.router)
from stock_agents.api import market_signals
app.include_router(market_signals.router)
app.include_router(account.router)
app.include_router(admin.router)
app.include_router(job_routes.router)
app.include_router(diagnostics.router)
app.include_router(screener.router)
app.include_router(ranker.router)
app.include_router(stock_profile.router)
app.include_router(personal.router)
from stock_agents.api import market_feed
app.include_router(market_feed.router)
app.include_router(broker.router)
OperationalDB = Annotated[ReadConnection, Depends(get_conn)]

CLASSIFICATION = """
    SELECT sector, industry
    FROM classification
    WHERE classification.ticker = {ticker}
      AND effective_date <= :asof AND known_date <= :asof
      AND LOWER(TRIM(source)) NOT LIKE 'factset%'
    ORDER BY effective_date DESC, known_date DESC, source
    LIMIT 1
"""


@app.middleware("http")
async def cache_policy(request: Request, call_next):
    response = await call_next(request)
    if not request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    details = [{key: error[key] for key in ("loc", "msg", "type")} for error in exc.errors()]
    return JSONResponse({"detail": details}, status_code=422)


def _page(name: str, title: str, **substitutions: str) -> HTMLResponse:
    """Render a page template inside the shared shell."""
    body = (TPL_DIR / f"{name}.html").read_text(encoding="utf-8")
    for k, v in substitutions.items():
        body = body.replace("{{" + k + "}}", v)
    nonce = token_urlsafe()
    html = SHELL.replace("{{PAGE_TITLE}}", title).replace("{{CONTENT}}", body)
    html = html.replace("<script>", f'<script nonce="{nonce}">')
    policy = (
        f"default-src 'self'; script-src 'nonce-{nonce}'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'"
    )
    return HTMLResponse(html, headers={"Content-Security-Policy": policy})


@app.exception_handler(Exception)
async def server_error(request: Request, _exc: Exception) -> JSONResponse:
    correlation = getattr(request.state, "request_id", None)
    headers = {"Cache-Control": "private, no-store"}
    if correlation:
        headers["X-Request-ID"] = correlation
    return JSONResponse({"detail": "Internal server error"}, status_code=500, headers=headers)


@app.get("/universe", response_model=list[UniverseRow], dependencies=[Depends(auth.require_market_data_user)])
async def universe(db: OperationalDB) -> list[dict[str, Any]]:
    rows = await db.fetch(
        f"""SELECT s.ticker, s.eodhd_symbol, cl.sector, cl.industry, company.company_name
            FROM symbology s
            LEFT JOIN LATERAL ({CLASSIFICATION.format(ticker="s.ticker")}) cl ON TRUE
            LEFT JOIN LATERAL (
                SELECT c.company_name FROM company_reference c
                WHERE c.ticker=s.ticker AND c.isin IS NOT DISTINCT FROM s.isin
                  AND c.observed_on<=:asof
                ORDER BY c.observed_on DESC, c.source LIMIT 1
            ) company ON TRUE
            WHERE s.active = TRUE
            ORDER BY s.ticker""",
        asof=date.today(),
    )
    return [
        {"ticker": ticker, "symbol": symbol, "sector": sector, "industry": industry, "company_name": company_name}
        for ticker, symbol, sector, industry, company_name in rows
    ]


CompanyDirectory = Annotated[list[dict], Depends(universe)]


@app.post("/screener/export", response_class=Response, responses={200: {"content": {XLSX: {}}}})
def export_screen(body: ScreenExport, user: CurrentUser, companies: CompanyDirectory):
    name, content = workbook(body, companies)
    return Response(content, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.post("/screener/email", status_code=204, response_class=Response)
@auth.limiter.limit("3/minute")
def email_screen(request: Request, body: ScreenEmail, user: CurrentUser, companies: CompanyDirectory):
    email_workbook(body, companies, user.email)
    return Response(status_code=204)


@app.get("/prices/{ticker}", response_model=list[PriceBar], dependencies=[Depends(auth.require_market_data_user)])
async def prices(
    ticker: str, db: OperationalDB, days: int = Query(90, ge=1, le=3650)
) -> list[dict[str, Any]]:
    rows = await db.fetch(
        """SELECT DISTINCT ON (date) date, open, high, low, close, adj_close, volume, source
           FROM prices_daily
           WHERE ticker = :ticker AND date BETWEEN :cutoff AND :today AND known_date <= :today
             AND (volume > 0 OR volume IS NULL) AND LOWER(TRIM(source)) NOT LIKE 'factset%'
           ORDER BY date, (source='angel_one') DESC, (source='eodhd') DESC, known_date DESC, source""",
        ticker=ticker.upper(),
        cutoff=date.today() - timedelta(days=days),
        today=date.today(),
    )
    if not rows:
        raise HTTPException(404, f"no prices for {ticker}")
    return [
        {"date": str(d), "open": o, "high": h, "low": lo, "close": cl, "adj_close": ac, "volume": v, "source": source}
        for d, o, h, lo, cl, ac, v, source in rows
    ]


def _news_timestamp(ts) -> str:
    if ts.tzinfo is not None:
        ts = ts.astimezone(UTC).replace(tzinfo=None)
    return str(ts)


@app.get("/news-status/{ticker}", dependencies=[Depends(auth.require_market_data_user)])
async def news_status(ticker: str, db: OperationalDB) -> dict:
    import json
    rows = await db.fetch("""SELECT ended_at, status, warnings FROM run_log
        WHERE job='free_news' ORDER BY ended_at DESC LIMIT 1""")
    counts = await db.fetch("""SELECT count(*),max(published_at) FROM news
        WHERE ticker=:ticker AND source='The Economic Times RSS'""", ticker=ticker.upper())
    latest = rows[0] if rows else None
    details = json.loads(latest[2]) if latest and latest[2] else {}
    return {"status": latest[1] if latest else "not_run",
            "updated_at": str(latest[0])+"Z" if latest else None,
            "feeds_ok": details.get("feeds_ok",0), "feeds_total": details.get("feeds_total",4),
            "articles": counts[0][0], "latest_article": _news_timestamp(counts[0][1]) if counts[0][1] else None}


@app.get("/news/{ticker}", response_model=list[NewsItem], dependencies=[Depends(auth.require_market_data_user)])
async def news(
    ticker: str, db: OperationalDB, limit: int = Query(20, ge=1, le=200)
) -> list[dict[str, Any]]:
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
    rows = await db.fetch(
        """SELECT published_at, headline, source, url, polarity, pos, neg, neu
           FROM news
           WHERE ticker = :ticker AND LOWER(TRIM(COALESCE(source, ''))) NOT LIKE 'factset%'
           ORDER BY published_at DESC, (polarity IS NULL), news_id
           LIMIT :limit""",
        ticker=ticker.upper(),
        limit=limit * 5,
    )
    unique, seen = [], set()
    for row in rows:
        ts, headline, source, url, *_ = row
        try:
            parts = urlsplit(url or "")
            query = urlencode(sorted((k,v) for k,v in parse_qsl(parts.query)
                if not k.lower().startswith("utm_") and k not in ("from","source")))
            canonical = urlunsplit((parts.scheme.lower(),parts.netloc.lower(),parts.path,query,""))
        except ValueError:
            canonical = ""
        key = canonical or f"{ts.date()}:{(headline or '').strip().casefold()}"
        if key not in seen:
            seen.add(key)
            unique.append(row)
        if len(unique) == limit:
            break
    return [
        {
            "published_at": _news_timestamp(ts),
            "headline": h,
            "source": s,
            "url": u,
            "polarity": p,
            "pos": po,
            "neg": ne,
            "neu": nu,
        }
        for ts, h, s, u, p, po, ne, nu in unique
    ]


@app.get("/sentiment/{ticker}", response_model=list[SentimentDay], dependencies=[Depends(auth.require_market_data_user)])
async def sentiment(
    ticker: str, db: OperationalDB, days: int = Query(90, ge=1, le=730)
) -> list[dict[str, Any]]:
    rows = await db.fetch(
        """SELECT effective_date, polarity, n_headlines
           FROM sentiment_daily
           WHERE ticker = :ticker AND effective_date >= :cutoff
             AND source='free_news_finbert'
           ORDER BY effective_date, source""",
        ticker=ticker.upper(),
        cutoff=date.today() - timedelta(days=days),
    )
    return [{"date": str(d), "polarity": p, "n_headlines": n} for d, p, n in rows]


@app.get("/agents/{name}", response_model=list[AgentScoreRow])
async def agent_scores(
    name: str, db: OperationalDB, _user: CurrentUser, asof: date | None = None
) -> list[dict[str, Any]]:
    if asof is None:
        [(asof,)] = await db.fetch(
            "SELECT MAX(date) FROM agent_scores WHERE agent = :name", name=name
        )
        if asof is None:
            return []
    rows = await db.fetch(
        f"""SELECT s.ticker, s.score, s.passes, cl.sector, cl.industry
            FROM agent_scores s
            LEFT JOIN LATERAL ({CLASSIFICATION.format(ticker="s.ticker")}) cl ON TRUE
            WHERE s.agent = :name AND s.date = :asof
            ORDER BY s.score DESC NULLS LAST, s.ticker""",
        name=name,
        asof=asof,
    )
    return [
        {"ticker": t, "score": sc, "imputed": not bool(p), "sector": sec, "industry": ind}
        for t, sc, p, sec, ind in rows
    ]


@app.get("/scores/{ticker}", response_model=list[AgentHistoryPoint])
async def score_history(
    ticker: str, db: OperationalDB, _user: CurrentUser, days: int = Query(365, ge=1, le=3650)
) -> list[dict[str, Any]]:
    today = date.today()
    rows = await db.fetch(
        """SELECT date, agent, score, passes FROM agent_scores
           WHERE ticker = :ticker AND date BETWEEN :start AND :end
           ORDER BY date, agent""",
        ticker=ticker.upper(), start=today - timedelta(days=days), end=today,
    )
    return [{"date": day, "agent": agent, "score": score, "imputed": passes is False}
            for day, agent, score, passes in rows]


@app.get("/combine", response_model=CombineOut, response_model_exclude_unset=True)
async def combine(
    db: OperationalDB,
    _user: CurrentUser,
    options: Annotated[CombineQuery, Query()],
) -> dict[str, Any]:
    from starlette.concurrency import run_in_threadpool

    from stock_agents.engine.combiner import rank_scores

    asof = options.asof
    if asof is None:
        [(asof,)] = await db.fetch("SELECT MAX(date) FROM agent_scores")
        asof = asof or date.today()
    rows = await db.fetch(
        f"""SELECT s.ticker, s.agent, s.score, cl.sector
            FROM agent_scores s
            LEFT JOIN LATERAL ({CLASSIFICATION.format(ticker="s.ticker")}) cl ON TRUE
            WHERE s.date = :asof
            ORDER BY s.ticker, s.agent""",
        asof=asof,
    )
    scores = [(t, agent, score) for t, agent, score, _ in rows]
    sectors = sorted({(t, sector) for t, _, _, sector in rows}, key=lambda row: row[0])
    overrides = options.model_dump(
        include={"technical", "sentiment", "momentum", "fundamental"}, exclude_none=True
    )
    try:
        return await run_in_threadpool(
            rank_scores, scores, sectors, asof, options.n, options.mode, custom_weights=overrides
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


# --------------------------------------------------------------- Pages (HTML)
@app.get("/login", include_in_schema=False)
def page_login() -> HTMLResponse:
    return _page("login", "Sign in")


@app.get("/", include_in_schema=False)
def page_home() -> HTMLResponse:
    return _page("home", "Home")


@app.get("/dashboard", include_in_schema=False)
def page_dashboard() -> HTMLResponse:
    return _page("dashboard", "Dashboard")


@app.get("/stocks", include_in_schema=False)
async def page_stocks(db: OperationalDB) -> HTMLResponse:
    [(n,)] = await db.fetch("SELECT COUNT(*) FROM symbology WHERE active = TRUE")
    return _page("stocks", "Stocks", N_TICKERS=str(n))


@app.get("/stocks/{ticker}", include_in_schema=False)
def page_stock_detail(ticker: str) -> HTMLResponse:
    tk = escape(ticker.upper())
    return _page("stock_detail", tk, TICKER=tk)


@app.get("/backtest", include_in_schema=False)
def page_backtest() -> HTMLResponse:
    return _page("backtest", "Backtest")


@app.get("/methodology", include_in_schema=False)
def page_methodology() -> HTMLResponse:
    return _page("methodology", "Methodology")


@app.get("/_admin/rq", include_in_schema=False)
async def queue_dashboard(request: Request, _admin: AdminUser) -> RedirectResponse:
    return RedirectResponse(request.url.replace(path=request.url.path + "/"), status_code=307)


app.mount("/_admin/rq", admin_dashboard, name="rq-dashboard")
# Static assets (styles.css, future bundled JS, favicon)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.add_middleware(ObserveRequests)

from stock_agents.api import us_market
app.include_router(us_market.router)
