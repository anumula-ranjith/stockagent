"""Import a read-only DuckDB snapshot into a bootstrapped PostgreSQL database."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC
from itertools import groupby
from pathlib import Path

import duckdb
from sqlalchemy import DateTime, create_engine, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine

from stock_agents.common.config import load_settings
from stock_agents.storage.postgres import Base, database_url
from stock_agents.storage.schema import ALL_TABLES

BATCH_SIZE = 1000


def _source_rows(source, table, names):
    columns = ", ".join(f'"{name}"' for name in names)
    order = ' ORDER BY "date"' if table.name == "prices_daily" else ""
    rows = source.execute(f'SELECT {columns} FROM "{table.name}"{order}')
    while batch := rows.fetchmany(BATCH_SIZE):
        yield from batch


def _batches(rows):
    batch = []
    for row in rows:
        batch.append(row)
        if len(batch) == BATCH_SIZE:
            yield batch
            batch = []
    if batch:
        yield batch


def migrate(path: Path, engine: Engine) -> list[tuple[str, int, int]]:
    """Return source and target counts for each imported warehouse table."""
    counts = []
    with duckdb.connect(str(path), read_only=True) as source, engine.begin() as target:
        source.execute("BEGIN TRANSACTION")
        # Serialize import runs, including reconciliation of the keyless log.
        target.exec_driver_sql("SELECT pg_advisory_xact_lock(490122860)")
        for definition in ALL_TABLES:
            table = Base.metadata.tables[definition.name]
            names = list(table.columns.keys())
            rows = _source_rows(source, table, names)
            if table.name == "quality_log":
                target.exec_driver_sql("LOCK TABLE quality_log IN SHARE ROW EXCLUSIVE MODE")
                existing = Counter(tuple(row) for row in target.execute(select(table)))
                statement = table.insert()
            else:
                existing = Counter()
                statement = insert(table).on_conflict_do_nothing(
                    index_elements=list(table.primary_key.columns)
                )

            groups = (rows,)
            if table.name == "prices_daily":
                date_index = names.index("date")
                monthly = groupby(rows, lambda row, i=date_index: row[i].replace(day=1))
                groups = (group for _, group in monthly)
            tz_columns = [
                col.name
                for col in table.columns
                if isinstance(col.type, DateTime) and col.type.timezone
            ]
            source_count = 0
            for group in groups:
                for batch in _batches(group):
                    source_count += len(batch)
                    records = []
                    for row in batch:
                        if existing[row]:
                            existing[row] -= 1
                            continue
                        record = dict(zip(names, row, strict=True))
                        for name in tz_columns:
                            value = record[name]
                            if value is not None and value.tzinfo is None:
                                record[name] = value.replace(tzinfo=UTC)
                        records.append(record)
                    if records:
                        target.execute(statement, records)
            target_count = target.scalar(select(func.count()).select_from(table))
            counts.append((table.name, source_count, target_count))
        source.execute("COMMIT")
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duckdb", type=Path, default=load_settings().paths.duckdb)
    args = parser.parse_args()
    engine = create_engine(database_url("psycopg2"), hide_parameters=True)
    try:
        counts = migrate(args.duckdb, engine)
    finally:
        engine.dispose()

    print(f"{'Table':<24} {'DuckDB':>12} {'PostgreSQL':>12} {'Difference':>12}")
    for name, source_count, target_count in counts:
        print(
            f"{name:<24} {source_count:>12,} {target_count:>12,} {target_count - source_count:>12,}"
        )
    return int(any(source_count != target_count for _, source_count, target_count in counts))


if __name__ == "__main__":
    raise SystemExit(main())
