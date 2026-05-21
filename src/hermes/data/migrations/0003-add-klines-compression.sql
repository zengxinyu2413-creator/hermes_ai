-- migration: 0003-add-klines-compression
-- author: Hermes Project
-- date: 2026-05-21
-- description: Add compression settings and automatic compression policy to klines.
--              Chunks older than 30 days are compressed automatically.
--              No retention policy — klines is kept permanently per timescaledb_schema.md §5.6.
-- depends-on: 0002-create-klines-hypertable
-- estimated-duration: <5 seconds
-- requires-downtime: no
-- destructive: no

BEGIN;

ALTER TABLE klines SET (
    timescaledb.compress,
    timescaledb.compress_orderby = 'open_time DESC',
    timescaledb.compress_segmentby = 'symbol, interval'
);

SELECT add_compression_policy('klines', INTERVAL '30 days');

COMMIT;
