-- migration: 0009-create-trades-hypertable
-- author: Hermes Project
-- date: 2026-05-21
-- description: Convert trades to a TimescaleDB hypertable, partitioned by trade_time.
--              No compression policy here — that lands in 0010.
-- depends-on: 0008-create-trades
-- estimated-duration: <5 seconds
-- requires-downtime: no
-- destructive: no

BEGIN;

SELECT create_hypertable('trades', 'trade_time', chunk_time_interval => INTERVAL '1 day');

COMMIT;
