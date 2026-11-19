"""Schema history for the operational PostgreSQL database."""

from alembic import context
from sqlalchemy import create_engine, pool

from stock_agents.jobs import pipeline_models  # noqa: F401 (register the operational tables)
from stock_agents.storage.postgres import Base, database_url


def run_migrations() -> None:
    url = database_url("psycopg2")
    if context.is_offline_mode():
        context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
        with context.begin_transaction():
            context.run_migrations()
        return

    engine = create_engine(url, poolclass=pool.NullPool, hide_parameters=True)
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=Base.metadata,
                compare_type=True,
                compare_server_default=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


run_migrations()
