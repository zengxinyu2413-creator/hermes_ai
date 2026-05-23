-- migration: 0010-add-trades-compression
-- author: Hermes Project
-- date: 2026-05-21
-- description: Add compression settings and automatic compression policy to trades.
--              Chunks older than 7 days are compressed automatically.
--              Retention policy (30 days) lands in a later migration.
--              Note: compress_orderby uses two columns (trade_time DESC, trade_id DESC)
--              because multiple trades can share the same trade_time at high frequency;
--              trade_id provides deterministic ordering within a compressed batch (§7.3 / §7.5).
-- depends-on: 0009-create-trades-hypertable
-- estimated-duration: <5 seconds
-- requires-downtime: no
-- destructive: no


ALTER TABLE trades SET (
    timescaledb.compress,
    timescaledb.compress_orderby = 'trade_time DESC, trade_id DESC',
    timescaledb.compress_segmentby = 'symbol'
);

SELECT add_compression_policy('trades', INTERVAL '7 days');

