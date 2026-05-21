-- migration: 0006-add-book-tickers-compression (rollback)
-- description: Remove book_tickers compression policy, decompress any existing chunks,
--              and disable compression settings. Ordered steps:
--              (1) remove policy, (2) decompress any compressed chunks (I/O-heavy if
--              compressed data exists — do not run on large live tables without planning),
--              (3) disable compress. All three steps are transaction-safe.
--              Step 2 is a no-op if no compressed chunks exist.
-- destructive: no (rows are preserved; compression metadata and policy are removed.
--              WARNING: decompression is an I/O-intensive operation if compressed chunks exist)
-- pre-check: confirm no application writers are running against book_tickers before rollback

BEGIN;

SELECT remove_compression_policy('book_tickers', if_exists => true);

SELECT decompress_chunk(c) FROM show_chunks('book_tickers') c;

ALTER TABLE book_tickers SET (timescaledb.compress = false);

COMMIT;
