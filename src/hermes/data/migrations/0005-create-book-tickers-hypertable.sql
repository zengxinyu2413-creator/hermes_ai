-- migration: 0005-create-book-tickers-hypertable
-- author: Hermes Project
-- date: 2026-05-21
-- description: Convert book_tickers to a TimescaleDB hypertable, partitioned by received_at.
--              No compression policy here — that lands in a later migration.
-- depends-on: 0004-create-book-tickers
-- estimated-duration: <5 seconds
-- requires-downtime: no
-- destructive: no


SELECT create_hypertable('book_tickers', 'received_at', chunk_time_interval => INTERVAL '1 day');

