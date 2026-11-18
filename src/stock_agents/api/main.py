"""FastAPI entry point.

For now it serves the UI (``src/stock_agents/ui/demo.html``) at ``/`` and a
``/health`` endpoint. Phase 8 adds the real endpoints
(``/universe``, ``/agents/{name}``, ``/combine``, ``/backtest``) that the
HTML will `fetch()` instead of the current client-side ``simulate()`` block.

Run:
    uvicorn stock_agents.api.main:app --port 8700 --reload
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

UI_DIR = Path(__file__).resolve().parent.parent / "ui"
DEMO_HTML = UI_DIR / "demo.html"

app = FastAPI(title="stock-agents", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "ui": "demo" if DEMO_HTML.exists() else "missing"}


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(DEMO_HTML, media_type="text/html")


# Also serve the ui/ folder at /static so demo.html can reference sibling files
# (future JS/CSS extracted from the inline <style>/<script> blocks).
app.mount("/static", StaticFiles(directory=UI_DIR), name="static")
