"""Capture the NSE cash session from Angel One at 15:16 India time."""

import json
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy.dialects.postgresql import insert

from stock_agents.common.config import load_settings
from stock_agents.ingest.price_provider import angel_capture_result, price_provider
from stock_agents.jobs.pipeline_stages import warehouse_writer
from stock_agents.jobs.pipelines import market_calendar
from stock_agents.jobs.queue import _redis, redis_url
from stock_agents.storage.postgres import Base

IST = ZoneInfo("Asia/Kolkata")
CAPTURE_AT = time(15, 16)


def in_capture_window(now: datetime) -> bool:
    local = now.astimezone(IST)
    if not CAPTURE_AT <= local.time() < time(15, 30):
        return False
    session = market_calendar().schedule(local.date(), local.date())
    return not session.empty and session.iloc[0].market_open <= local < session.iloc[0].market_close


def run_capture(now: datetime) -> dict:
    day = now.astimezone(IST).date()
    if price_provider() != "angel_one":
        return {"status": "skipped", "trade_date": str(day), "reason": "A different price provider is configured"}
    if not in_capture_window(now):
        return {"status": "skipped", "trade_date": str(day), "reason": "Outside the 15:16 NSE capture window"}

    from stock_agents.ingest.angel_prices import refresh_angel_prices

    with warehouse_writer() as conn:
        result = angel_capture_result(conn, day)
        if result["status"] != "ok":
            result = refresh_angel_prices(conn, day)
            log = Base.metadata.tables["run_log"]
            record = insert(log).values(
                run_id=f"angel-market-{day}", job="angel_market", started_at=now.astimezone(UTC).replace(tzinfo=None),
                ended_at=datetime.now(UTC).replace(tzinfo=None), status=result["status"],
                rows_written=result["written"], warnings=json.dumps(result),
            )
            conn.execute(record.on_conflict_do_update(
                index_elements=[log.c.run_id],
                set_={name: record.excluded[name] for name in ("ended_at", "status", "rows_written", "warnings")},
            ))
    # Publish only after commit. A restart after a publication failure reuses the snapshot.
    _redis(redis_url()).incr("quantora:market-generation")
    return result


def main() -> int:
    now = datetime.now(UTC)
    try:
        result = run_capture(now)
    except Exception as exc:
        result = {"status": "failed", "error_type": type(exc).__name__}
        # A broker error rolls back the price transaction. Record the attempt separately.
        try:
            day = now.astimezone(IST).date()
            if in_capture_window(now) and price_provider() == "angel_one":
                with warehouse_writer() as conn:
                    log = Base.metadata.tables["run_log"]
                    failure = insert(log).values(
                        run_id=f"angel-market-{day}", job="angel_market", status="failed",
                        started_at=now.replace(tzinfo=None), ended_at=datetime.now(UTC).replace(tzinfo=None),
                        rows_written=0, warnings=json.dumps({**result, "trade_date": str(day)}),
                    )
                    conn.execute(failure.on_conflict_do_update(
                        index_elements=[log.c.run_id],
                        set_={name: failure.excluded[name] for name in ("ended_at", "status", "warnings")},
                        where=log.c.status != "ok",
                    ))
        except Exception as audit_error:
            result["audit_error_type"] = type(audit_error).__name__
    report = {"at": now.isoformat(), **result}
    with (load_settings().paths.log_dir / "angel_market.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(report) + "\n")
    print(json.dumps(report))
    return int(result["status"] not in {"ok", "skipped"})


if __name__ == "__main__":
    raise SystemExit(main())
