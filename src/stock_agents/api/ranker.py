"""Authenticated research controls and audited portfolio replay."""

from datetime import date
from time import monotonic
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import or_, select

from stock_agents.api.auth import AdminUser, CurrentUser, Session, admin_rate_key, limiter
from stock_agents.api.job_routes import _enqueue
from stock_agents.api.schemas import BacktestJobRef
from stock_agents.common.snapshot_cache import SnapshotCache
from stock_agents.engine.ranker import RankSettings, to_payload
from stock_agents.engine.ranker_inputs import snapshot_inputs
from stock_agents.engine.ranker_replay import Replay
from stock_agents.ingest.screen_indices import INDEX_FILES
from stock_agents.engine.rank_universe import UniverseSelection, universe_metadata
from stock_agents.engine.stock_analysis import stock_analysis
from stock_agents.storage.postgres import JobRun
from stock_agents.storage.warehouse import connect

router = APIRouter(prefix="/ranker")


_inputs = SnapshotCache()


def _cached_inputs(asof: date, generation: int, subject: str | None = None):
    def load():
        with connect(read_only=True) as conn:
            return snapshot_inputs(conn, asof, subject=subject)
    return _inputs.get((asof, subject), load)


@router.get("/snapshot")
def default_snapshot(_user: CurrentUser, asof: date | None = None):
    return tuned_snapshot(RankSettings(), _user, asof)


def _snapshot_date(asof: date | None):
    asof = asof or date.today()
    if asof > date.today():
        raise HTTPException(422, "Select a ranking date on or before today.")
    return asof


_universe_cache = SnapshotCache()


def _universe_metadata(asof):
    with connect(read_only=True) as conn:
        return universe_metadata(conn, asof)


@router.post("/snapshot")
def tuned_snapshot(
    settings: RankSettings, _user: CurrentUser, asof: date | None = None,
    universe_filters: bool = False, index_code: str = "NIFTY500",
    cap: Literal["", "large", "mid", "small"] = "", industry: str = "", fo_only: bool = False,
):
    asof = _snapshot_date(asof)
    raw, price_date = _cached_inputs(asof, int(monotonic() // 120))
    if not (universe_filters or index_code != "NIFTY500" or cap or industry or fo_only):
        return to_payload(raw, settings, asof, price_date)
    groups, industries = _universe_cache.get(asof, lambda: _universe_metadata(asof))
    options = {"NIFTY500": "Nifty 500", **{c: spec[0] for c, spec in INDEX_FILES.items() if c in groups}}
    industry_options = sorted({industries[t] for t in raw.index if t in industries})
    selection = UniverseSelection(index_code=index_code, cap=cap, industry=industry, fo_only=fo_only)
    eligible = selection.eligible(raw.index, groups, industries)
    payload = to_payload(raw.loc[raw.index.isin(eligible)], settings, asof, price_date)
    return {**payload, "index_options": options, "industries": industry_options}


@router.post("/stock/{ticker}")
def stock_agent_analysis(
    ticker: str, settings: RankSettings, _user: CurrentUser, asof: date | None = None
):
    asof = _snapshot_date(asof)
    generation = int(monotonic() // 120)
    raw, price_date = _cached_inputs(asof, generation)
    ticker = ticker.strip().upper()
    if not raw.empty and ticker not in raw.index:
        comparison, comparison_date = _cached_inputs(asof, generation, ticker)
        if ticker in comparison.index:
            raw, price_date = comparison, comparison_date
    return stock_analysis(raw, settings, asof, price_date, ticker)


@router.get("/latest")
async def latest_replay(user: CurrentUser, session: Session):
    query = (
        select(JobRun.result_data)
        .where(
            JobRun.job_type == "backtest",
            JobRun.status == "finished",
            JobRun.payload["ranker"].is_not(None),
            JobRun.result_data.is_not(None),
            or_(JobRun.user_id == user.id, JobRun.user_id.is_(None)),
        )
        .order_by(JobRun.finished_at.desc(), JobRun.id)
        .limit(1)
    )
    return await session.scalar(query) or {"note": "No tuned backtest has finished yet."}


@router.post("/backtest", status_code=202, response_model=BacktestJobRef)
@limiter.limit("3/hour", key_func=admin_rate_key)
async def start_replay(
    request: Request, response: Response, user: AdminUser, session: Session, config: Replay
):
    if config.end > date.today():
        raise HTTPException(422, "Select an end date on or before today.")
    return await _enqueue(
        request, session, user, "backtest", {"ranker": config.model_dump(mode="json")}
    )
