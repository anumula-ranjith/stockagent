from datetime import date, datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from stock_agents.api.auth import CurrentUser
from stock_agents.api.ranker import tuned_snapshot
from stock_agents.engine.daily_picks import (
    IST, PickConfig, closed_through, performance, store_batch,
)
from stock_agents.storage.warehouse import connect

router = APIRouter(prefix="/ranker/daily-picks", tags=["daily portfolio"])


class Book(BaseModel):
    longs: list[str] = Field(max_length=50)
    shorts: list[str] = Field(max_length=50)


class SaveRequest(PickConfig):
    signal_date: date
    book: Book


@router.get("")
def history(user: CurrentUser):
    with connect(read_only=True) as conn:
        schedule = conn.execute("SELECT config FROM daily_pick_schedules WHERE user_id=?", [user.id]).scalar()
        days = conn.execute("""SELECT signal_date, origin, saved_at, config->'selection' AS selection,
            jsonb_array_length(book->'longs') AS longs, jsonb_array_length(book->'shorts') AS shorts
            FROM daily_pick_batches WHERE user_id=? ORDER BY signal_date DESC""", [user.id]).mappings().all()
    return {"schedule": schedule, "days": [dict(row) for row in days]}


@router.put("/schedule")
def enable_schedule(config: PickConfig, user: CurrentUser):
    with connect() as conn:
        conn.execute("""INSERT INTO daily_pick_schedules(user_id, starts_on, config)
            VALUES (?, ?, CAST(? AS jsonb)) ON CONFLICT (user_id) DO UPDATE
            SET starts_on=excluded.starts_on, config=excluded.config
            WHERE daily_pick_schedules.config<>excluded.config""",
            [user.id, datetime.now(IST).date(), config.model_dump_json()])
    return {"enabled": True}


@router.delete("/schedule")
def disable_schedule(user: CurrentUser):
    with connect() as conn:
        conn.execute("DELETE FROM daily_pick_schedules WHERE user_id=?", [user.id])
    return {"enabled": False}


@router.post("")
def add_batch(body: SaveRequest, user: CurrentUser):
    day = body.signal_date
    if day > closed_through():
        raise HTTPException(422, "Choose a trading session that has closed.")
    config = PickConfig(settings=body.settings, selection=body.selection)
    expected = body.book.model_dump()
    with connect() as conn:
        existing = conn.execute("SELECT 1 FROM daily_pick_batches WHERE user_id=? AND signal_date=?",
                                [user.id, day]).scalar()
        if existing:
            return {"added": False, "signal_date": day}
        snapshot = tuned_snapshot(config.settings, user, day, universe_filters=True,
                                  **config.selection.model_dump())
        book = snapshot["books"]["combined"]
        if snapshot["price_date"] != day.isoformat() or not any(book.values()):
            raise HTTPException(422, "No Combined picks are available for that trading session.")
        if book != expected:
            raise HTTPException(409, "The Combined picks changed. Refresh the rankings and try again.")
        added = store_batch(conn, user.id, day, config, book, "manual")
    return {"added": added, "signal_date": day}


@router.get("/{day}")
def backtest(day: date, user: CurrentUser, through: date | None = None):
    latest = closed_through()
    end = through or latest
    if end < day or end > latest:
        raise HTTPException(422, "Choose an end date between the ranking date and the latest completed close.")
    with connect(read_only=True) as conn:
        book = conn.execute("SELECT book FROM daily_pick_batches WHERE user_id=? AND signal_date=?",
                            [user.id, day]).scalar()
        if book is None:
            raise HTTPException(404, "Daily portfolio not found.")
        return performance(conn, day, book, end)
