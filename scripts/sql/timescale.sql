CREATE EXTENSION IF NOT EXISTS timescaledb;

SELECT create_hypertable(
    'prices_daily',
    by_range('date', INTERVAL '30 days'),
    create_default_indexes => FALSE,
    if_not_exists => TRUE,
    migrate_data => TRUE
);

ALTER TABLE prices_daily SET (
    timescaledb.enable_columnstore = true,
    timescaledb.segmentby = 'ticker',
    timescaledb.orderby = 'date DESC'
);

CALL add_columnstore_policy('prices_daily', after => INTERVAL '90 days', if_not_exists => TRUE);
