"""FastAPI app: shell-templated website + JSON endpoints.

Pages (HTML, all wrapped in templates/_shell.html):
  GET /                         Home / landing
  GET /dashboard                Four-agent dashboard
  GET /stocks                   Universe explorer
  GET /stocks/{ticker}          Per-ticker detail
  GET /backtest                 Backtest UI
  GET /methodology              Methodology page
  GET /demo                     Original seeded-simulation demo (reference)

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

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from stock_agents.common import config as _config

UI_DIR = Path(__file__).resolve().parent.parent / "ui"
TPL_DIR = UI_DIR / "templates"
STATIC_DIR = UI_DIR / "static"
DEMO_HTML = UI_DIR / "demo.html"
SHELL = (TPL_DIR / "_shell.html").read_text(encoding="utf-8")

app = FastAPI(title="stock-agents", version="0.3.0")


def _page(name: str, title: str, **substitutions: str) -> HTMLResponse:
    """Render a page template inside the shared shell."""
    body = (TPL_DIR / f"{name}.html").read_text(encoding="utf-8")
    for k, v in substitutions.items():
        body = body.replace("{{" + k + "}}", v)
    html = SHELL.replace("{{PAGE_TITLE}}", title).replace("{{CONTENT}}", body)
    return HTMLResponse(html)


def _conn() -> duckdb.DuckDBPyConnection:
    s = _config.load_settings()
    return duckdb.connect(str(s.paths.duckdb), read_only=True)


# --------------------------------------------------------------- Health / JSON
@app.get("/health")
def health() -> dict[str, Any]:
    try:
        c = _conn()
        try:
            nt = c.execute("SELECT COUNT(*) FROM symbology WHERE active = TRUE").fetchone()[0]
            np = c.execute("SELECT COUNT(*) FROM prices_daily").fetchone()[0]
            nticks = c.execute("SELECT COUNT(DISTINCT ticker) FROM prices_daily").fetchone()[0]
        finally:
            c.close()
        return {"status": "ok", "tickers": nt, "tickers_with_prices": nticks, "price_rows": np}
    except Exception as e:
        return {"status": "degraded", "error": str(e)}


@app.get("/universe")
def universe() -> list[dict[str, Any]]:
    c = _conn()
    try:
        rows = c.execute(
            """SELECT s.ticker, s.eodhd_symbol, cl.sector, cl.industry
               FROM symbology s
               LEFT JOIN classification cl
                 ON cl.ticker = s.ticker
                AND cl.effective_date = (
                    SELECT MAX(effective_date) FROM classification cl2
                    WHERE cl2.ticker = s.ticker
                )
               WHERE s.active = TRUE
               ORDER BY s.ticker"""
        ).fetchall()
    finally:
        c.close()
    return [
        {"ticker": t, "symbol": sym, "sector": sector, "industry": ind}
        for t, sym, sector, ind in rows
    ]


@app.get("/prices/{ticker}")
def prices(ticker: str, days: int = Query(90, ge=1, le=3650)) -> list[dict[str, Any]]:
    cutoff = date.today() - timedelta(days=days)
    c = _conn()
    try:
        rows = c.execute(
            """SELECT date, open, high, low, close, adj_close, volume
               FROM prices_daily
               WHERE ticker = ? AND date >= ?
               ORDER BY date""",
            [ticker.upper(), cutoff],
        ).fetchall()
    finally:
        c.close()
    if not rows:
        raise HTTPException(404, f"no prices for {ticker}")
    return [
        {"date": str(d), "open": o, "high": h, "low": lo, "close": cl, "adj_close": ac, "volume": v}
        for d, o, h, lo, cl, ac, v in rows
    ]


@app.get("/news/{ticker}")
def news(ticker: str, limit: int = Query(20, ge=1, le=200)) -> list[dict[str, Any]]:
    c = _conn()
    try:
        rows = c.execute(
            """SELECT published_at, headline, source, url, polarity, pos, neg, neu
               FROM news
               WHERE ticker = ?
               ORDER BY published_at DESC
               LIMIT ?""",
            [ticker.upper(), limit],
        ).fetchall()
    finally:
        c.close()
    return [
        {"published_at": str(ts), "headline": h, "source": s, "url": u,
         "polarity": p, "pos": po, "neg": ne, "neu": nu}
        for ts, h, s, u, p, po, ne, nu in rows
    ]


@app.get("/sentiment/{ticker}")
def sentiment(ticker: str, days: int = Query(90, ge=1, le=730)) -> list[dict[str, Any]]:
    cutoff = date.today() - timedelta(days=days)
    c = _conn()
    try:
        rows = c.execute(
            """SELECT effective_date, polarity, n_headlines
               FROM sentiment_daily
               WHERE ticker = ? AND effective_date >= ?
               ORDER BY effective_date""",
            [ticker.upper(), cutoff],
        ).fetchall()
    finally:
        c.close()
    return [{"date": str(d), "polarity": p, "n_headlines": n} for d, p, n in rows]


@app.get("/agents/{name}")
def agent_scores(name: str, asof: str | None = None) -> list[dict[str, Any]]:
    from stock_agents.engine.scores import latest_agent_scores

    c = _conn()
    try:
        return latest_agent_scores(c, name=name, asof=asof)
    finally:
        c.close()


@app.get("/combine")
def combine(
    asof: str | None = None,
    n: int = Query(10, ge=1, le=50),
    mode: str = Query("weighted"),
) -> dict[str, Any]:
    from stock_agents.engine.combiner import combine_latest

    c = _conn()
    try:
        return combine_latest(c, asof=asof, n_per_side=n, mode=mode)
    finally:
        c.close()


@app.get("/backtest/latest")
def backtest_latest() -> dict[str, Any]:
    from stock_agents.engine.backtest import latest_summary

    return latest_summary()


@app.post("/backtest/run")
def backtest_run(
    start: str = Query(...), end: str = Query(...), n: int = Query(10, ge=3, le=30)
) -> dict[str, Any]:
    from stock_agents.engine.backtest import run_backtest

    # backtest needs a writable connection (it doesn't actually write, but
    # engine.scores uses INSERT OR REPLACE when it computes score rows for
    # intermediate dates — if that's problematic, remove the insert and keep
    # scores purely in-memory. For now, use a read-only conn + bypass storage).
    s = _config.load_settings()
    conn = duckdb.connect(str(s.paths.duckdb), read_only=True)
    try:
        return run_backtest(
            conn,
            start=date.fromisoformat(start),
            end=date.fromisoformat(end),
            n_per_side=n,
        )
    finally:
        conn.close()


# --------------------------------------------------------------- Pages (HTML)
@app.get("/", include_in_schema=False)
def page_home() -> HTMLResponse:
    return _page("home", "Home")


@app.get("/dashboard", include_in_schema=False)
def page_dashboard() -> HTMLResponse:
    return _page("dashboard", "Dashboard")


@app.get("/stocks", include_in_schema=False)
def page_stocks() -> HTMLResponse:
    c = _conn()
    try:
        n = c.execute("SELECT COUNT(*) FROM symbology WHERE active = TRUE").fetchone()[0]
    finally:
        c.close()
    return _page("stocks", "Stocks", N_TICKERS=str(n))


@app.get("/stocks/{ticker}", include_in_schema=False)
def page_stock_detail(ticker: str) -> HTMLResponse:
    tk = ticker.upper()
    return _page("stock_detail", tk, TICKER=tk)


@app.get("/backtest", include_in_schema=False)
def page_backtest() -> HTMLResponse:
    return _page("backtest", "Backtest")


@app.get("/methodology", include_in_schema=False)
def page_methodology() -> HTMLResponse:
    return _page("methodology", "Methodology")


@app.get("/demo", include_in_schema=False)
def demo() -> FileResponse:
    return FileResponse(DEMO_HTML, media_type="text/html")


# Static assets (styles.css, future bundled JS, favicon)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
