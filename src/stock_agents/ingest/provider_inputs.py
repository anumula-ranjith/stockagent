"""Collect today's EODHD and FactSet ranking inputs for tradable Nifty 500 members."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from stock_agents.common.config import load_settings
from stock_agents.ingest.daily import _upsert
from stock_agents.ingest.provider_values import eodhd_rows, snapshot_rows
from stock_agents.jobs.queue import sync_engine
from stock_agents.sources.eodhd import EODHDAccountError, EODHDClient
from stock_agents.sources.factset import FactSetClient
from stock_agents.storage.postgres import Base

SNAPSHOT_LOCK = 490122863
MARKET_TZ = ZoneInfo("Asia/Kolkata")


def _fetch_eodhd(client, member):
    _, _, symbol = member
    try:
        data = client.ranking_fundamentals(symbol)
        return member, data or {}, None
    except EODHDAccountError as exc:
        return member, {}, str(exc)
    except Exception as exc:
        # Request exception messages can include an authenticated URL.
        return member, {}, type(exc).__name__


def _normalize_eodhd(results, observed):
    # An exchange share split may replace an ISIN without replacing the
    # listed security. Only accept aliases resolving to one FactSet regional ID.
    aliases = set()
    for (_, isin, _), data, _ in results:
        general = data.get("General") if isinstance(data, dict) else None
        old = general.get("ISIN") if isinstance(general, dict) else None
        if old and isin and old != isin:
            aliases.update([isin, old])
    identities = {}
    if aliases:
        try:
            identities = FactSetClient.from_env().regional_ids(sorted(aliases))
        except (RuntimeError, ValueError, KeyError, TypeError, OSError):
            pass  # Unverified mismatches remain pending. Other members can load.
    for (ticker, isin, _), data, error in results:
        if error:
            yield ticker, {}, error
            continue
        try:
            yield ticker, eodhd_rows(ticker, isin, data, observed, identities), None
        except (ValueError, AttributeError, TypeError) as exc:
            yield ticker, {}, type(exc).__name__


def _record(connection, run_id, started, state):
    table = Base.metadata.tables["run_log"]
    values = dict(
        job="nifty_provider_inputs",
        started_at=started,
        ended_at=datetime.now(UTC).replace(tzinfo=None),
        status=state["status"],
        rows_written=state["inserted"],
        warnings=json.dumps(state, sort_keys=True),
    )
    connection.execute(
        insert(table)
        .values(run_id=run_id, **values)
        .on_conflict_do_update(index_elements=[table.c.run_id], set_=values)
    )
    connection.commit()


def _save_batch(connection, results, state):
    by_table = defaultdict(list)
    complete = set(state["complete"])
    missing = set(state["no_data"])
    for ticker, rows, error in results:
        if error:
            state["errors"][ticker] = error
            continue
        state["errors"].pop(ticker, None)
        complete.add(ticker)
        if not any(rows.values()):
            missing.add(ticker)
        else:
            missing.discard(ticker)
        for table_name, records in rows.items():
            by_table[table_name].extend(records)
    for table_name, records in by_table.items():
        table = Base.metadata.tables[table_name]
        for start in range(0, len(records), 500):
            batch = records[start : start + 500]
            if batch[0]["source"] == "factset_formula":
                # A formula revision can correct today's snapshot. Prior dates
                # have different keys and remain available for PIT reads.
                state["inserted"] += _upsert(connection, table_name, batch)
                continue
            # Preserve the values actually observed on a date, including
            # first-observed earnings history from a subsequently revised feed.
            statement = insert(table).values(batch).on_conflict_do_nothing()
            state["inserted"] += connection.execute(statement).rowcount
    state["complete"], state["no_data"] = sorted(complete), sorted(missing)


def _load_provider(connection, name, members, observed):
    run_id = f"nifty-inputs-{name}-{observed}"
    previous = connection.execute(
        text("SELECT started_at, warnings FROM run_log WHERE run_id=:id"), {"id": run_id}
    ).first()
    started = previous.started_at if previous else datetime.now(UTC).replace(tzinfo=None)
    state = (
        json.loads(previous.warnings)
        if previous
        else dict(complete=[], no_data=[], errors={}, inserted=0)
    )
    revision = 3 if name == "factset_formula" else 1
    if state.get("revision", 1) != revision:
        state.update(complete=[], no_data=[], errors={})
    state["revision"] = revision
    done = set(state["complete"])
    pending = [m for m in members if m[0] not in done]
    needs_checkpoint = bool(pending) or state.get("status") != "ok"
    state.update(status="partial", universe_count=len(members))
    state.pop("provider_error", None)
    try:
        if pending and name == "eodhd":
            client = EODHDClient.from_env()
            # A fundamentals request costs ten units. Keep a margin for
            # concurrent price/news ingestion and limit concurrency per batch.
            reserve = max(100, int(load_settings().env("EODHD_NEWS_RESERVED_UNITS") or 12000))
            capacity = max(0, (client.remaining_calls() - reserve) // 10)
            if capacity < len(pending):
                state["provider_error"] = "EODHD daily quota insufficient for remaining symbols"
            pending = pending[:capacity]
            with ThreadPoolExecutor(max_workers=6) as pool:
                for start in range(0, len(pending), 30):
                    batch = pending[start : start + 30]
                    results = list(pool.map(lambda m: _fetch_eodhd(client, m), batch))
                    _save_batch(connection, _normalize_eodhd(results, observed), state)
                    _record(connection, run_id, started, state)
                    account_error = next(
                        (err for _, _, err in results if err and err.startswith("EODHD HTTP")), None
                    )
                    if account_error:
                        state["provider_error"] = account_error
                        break
        elif pending:
            client = FactSetClient.from_env()
            for start in range(0, len(pending), 40):
                batch = pending[start : start + 40]
                valid = [m for m in batch if m[1]]
                results = [(t, {}, "missing_isin") for t, isin, _ in batch if not isin]
                data = client.snapshot([m[1] for m in valid]) if valid else {}
                results.extend(
                    (t, snapshot_rows(t, data[isin], observed, name), None) for t, isin, _ in valid
                )
                _save_batch(connection, results, state)
                _record(connection, run_id, started, state)
    except (RuntimeError, ValueError, KeyError, TypeError, OSError) as exc:
        # The client includes only endpoint and status in its own HTTP errors.
        state["provider_error"] = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
    outstanding = {r[0] for r in members} - set(state["complete"])
    state["status"] = "partial" if outstanding else "ok"
    if needs_checkpoint:
        _record(connection, run_id, started, state)
    return dict(
        status=state["status"],
        members=len(members),
        attempted=len(set(state["complete"])),
        missing_data=state["no_data"],
        pending=sorted(outstanding),
        inserted=state["inserted"],
        errors=state["errors"],
        provider_error=state.get("provider_error"),
    )


def refresh_provider_inputs(*, due: bool = False):
    load_settings()
    observed = datetime.now(MARKET_TZ).date()
    with sync_engine().connect() as connection:
        if not connection.scalar(text("SELECT pg_try_advisory_lock(:k)"), {"k": SNAPSHOT_LOCK}):
            return {"status": "busy"}
        try:
            if due and not connection.scalar(
                text("""
                SELECT EXISTS (SELECT 1 FROM run_log WHERE run_id=:id
                AND status IN ('warning','ok') AND ended_at IS NOT NULL)
                """),
                {"id": f"nse-eod-{observed}"},
            ):
                return {"status": "awaiting_exchange"}
            members = connection.execute(
                text("""
                SELECT m.ticker,s.isin,s.eodhd_symbol FROM index_membership m
                JOIN symbology s USING (ticker) WHERE m.index_code='NIFTY500'
                AND m.known_on<=:day AND m.joined_on<=:day
                AND (m.left_on IS NULL OR m.left_on>:day) AND s.active ORDER BY m.ticker
                """),
                {"day": observed},
            ).all()
            if not members:
                raise RuntimeError("No active Nifty 500 membership has been observed")
            providers = {
                source: _load_provider(connection, source, members, observed)
                for source in ("factset_formula", "eodhd")
            }
            return {
                "date": str(observed),
                "providers": providers,
                "status": "ok"
                if all(p["status"] == "ok" for p in providers.values())
                else "partial",
            }
        finally:
            connection.rollback()
            connection.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": SNAPSHOT_LOCK})
            connection.commit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--due", action="store_true", help="Wait for today's exchange close")
    result = refresh_provider_inputs(due=parser.parse_args().due)
    print(json.dumps(result))
    raise SystemExit(1 if result["status"] == "partial" else 0)
