"""Immutable Combined picks and close-to-close paper performance."""
import json
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from stock_agents.engine.rank_universe import UniverseSelection, universe_metadata
from stock_agents.engine.ranker import RankSettings, score_book
from stock_agents.engine.ranker_inputs import snapshot_inputs
from stock_agents.storage.warehouse import connect

IST = ZoneInfo("Asia/Kolkata")
TRADED = """source IN ('eodhd','angel_one','nse_bhavcopy') AND close>0 AND volume>0
    AND EXISTS (SELECT 1 FROM index_membership m WHERE m.ticker=p.ticker AND m.index_code='NIFTY500')"""


class PickConfig(BaseModel):
    selection: UniverseSelection
    settings: RankSettings


def closed_through(cutoff=time(15, 30), now=None):
    local = (now or datetime.now(IST)).astimezone(IST)
    return local.date() if local.time() >= cutoff else local.date() - timedelta(days=1)


def combined_book(conn, day, config):
    raw, price_date = snapshot_inputs(conn, day)
    if raw.empty or price_date != day:
        return None
    if config.selection != UniverseSelection():
        groups, industries = universe_metadata(conn, day)
        eligible = config.selection.eligible(raw.index, groups, industries)
        raw = raw.loc[raw.index.isin(eligible)]
    if raw.empty:
        return {"longs": [], "shorts": []}
    _, books = score_book(raw, config.settings)
    return books["combined"]


def store_batch(conn, user_id, day, config, book, origin):
    return conn.execute("""
        INSERT INTO daily_pick_batches(user_id, signal_date, config, book, origin)
        VALUES (?, ?, CAST(? AS jsonb), CAST(? AS jsonb), ?)
        ON CONFLICT (user_id, signal_date) DO NOTHING
        RETURNING signal_date
    """, [user_id, day, config.model_dump_json(), json.dumps(book), origin]).first() is not None


def capture_due():
    """Catch up observed sessions since enrollment. A retry cannot replace a saved book."""
    end = closed_through(time(18, 30))
    with connect(read_only=True) as conn:
        due = conn.execute(f"""
            WITH sessions AS (
                SELECT DISTINCT date FROM prices_daily p
                WHERE date BETWEEN (SELECT min(starts_on) FROM daily_pick_schedules) AND ?
                AND known_date<=date AND {TRADED})
            SELECT s.user_id, d.date FROM daily_pick_schedules s
            JOIN sessions d ON d.date>=s.starts_on
            LEFT JOIN daily_pick_batches b ON b.user_id=s.user_id AND b.signal_date=d.date
            WHERE b.user_id IS NULL ORDER BY d.date, s.user_id
        """, [end]).all()
    saved = 0
    for user_id, day in due:
        with connect() as conn:
            current = conn.execute("""SELECT config FROM daily_pick_schedules
                WHERE user_id=? AND starts_on<=? FOR SHARE""", [user_id, day]).scalar()
            if current is None:
                continue
            config = PickConfig.model_validate(current)
            book = combined_book(conn, day, config)
            if book is not None:
                saved += store_batch(conn, user_id, day, config, book, "automatic")
    return saved


def performance(conn, signal_date: date, book: dict, through: date):
    entry, mark = conn.execute(f"""SELECT min(date), max(date) FROM prices_daily p
        WHERE date>? AND date<=? AND known_date<=? AND {TRADED}""",
        [signal_date, through, through]).one()
    symbols = book["longs"] + book["shorts"]
    quotes = {}
    if entry and symbols:
        rows = conn.execute("""SELECT ticker,date,
                max(adj_close) FILTER (WHERE source='eodhd' AND adj_close>0) AS adjusted,
                (array_agg(close ORDER BY (source='eodhd') DESC,(source='angel_one') DESC))[1] AS raw
            FROM prices_daily WHERE ticker=ANY(?) AND date IN (?,?) AND known_date<=?
              AND source IN ('eodhd','angel_one','nse_bhavcopy') AND close>0 AND volume>0
            GROUP BY ticker,date""", [symbols, entry, mark, through]).all()
        quotes = {(ticker, day): (adj, raw) for ticker, day, adj, raw in rows}
    positions = []
    for side in ("longs", "shorts"):
        for ticker in book[side]:
            first = quotes.get((ticker, entry), (None, None))
            last = quotes.get((ticker, mark), (None, None))
            adjusted = first[0] is not None and last[0] is not None
            start, finish = (first[0], last[0]) if adjusted else (first[1], last[1])
            move = (finish / start - 1) if start and finish else None
            positions.append({"ticker": ticker, "side": "Long" if side == "longs" else "Short",
                "entry": start, "mark": finish, "basis": "Adjusted" if adjusted else "Close",
                "return_value": -move if move is not None and side == "shorts" else move})
    returns = [p["return_value"] for p in positions if p["return_value"] is not None]
    return {"signal_date": signal_date, "entry_date": entry, "mark_date": mark, "through": through,
            "positions": positions, "priced": len(returns),
            "basket_return": sum(returns)/len(returns) if returns and len(returns)==len(positions) else None}
