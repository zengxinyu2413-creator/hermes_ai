-- migration: 0002-create-klines-hypertable
-- author: Hermes Project
-- date: 2026-05-21
-- description: Convert klines to a TimescaleDB hypertable, partitioned by open_time.
--              No compression policy here — that lands in 0003.
-- depends-on: 0001-create-klines
-- estimated-duration: <5 seconds
-- requires-downtime: no
-- destructive: no


SELECT create_hypertable('klines', 'open_time', chunk_time_interval => INTERVAL '7 days');

