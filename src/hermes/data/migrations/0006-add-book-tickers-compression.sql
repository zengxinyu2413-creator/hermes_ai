-- migration: 0006-add-book-tickers-compression
-- author: Hermes Project
-- date: 2026-05-21
-- description: Add compression settings and automatic compression policy to book_tickers.
--              Chunks older than 7 days are compressed automatically.
--              Retention policy (30 days) lands in a later migration.
-- depends-on: 0005-create-book-tickers-hypertable
-- estimated-duration: <5 seconds
-- requires-downtime: no
-- destructive: no


ALTER TABLE book_tickers SET (
    timescaledb.compress,
    timescaledb.compress_orderby = 'received_at DESC',
    timescaledb.compress_segmentby = 'symbol'
);

SELECT add_compression_policy('book_tickers', INTERVAL '7 days');

