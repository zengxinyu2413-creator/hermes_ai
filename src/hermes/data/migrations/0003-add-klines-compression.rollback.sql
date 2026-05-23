-- migration: 0003-add-klines-compression (rollback)
-- description: Remove klines compression policy and disable compression settings.
--              Order: (1) remove policy, (2) decompress any existing chunks,
--              (3) disable compress. All three steps are transaction-safe (confirmed
--              by local test 2026-05-21). Step 2 is a no-op if no compressed chunks exist.
-- destructive: no (rows are preserved; compression metadata and policy are removed)
-- pre-check: confirm no application writers are running against klines before rollback


SELECT remove_compression_policy('klines', if_exists => true);

SELECT decompress_chunk(c) FROM show_chunks('klines') c;

ALTER TABLE klines SET (timescaledb.compress = false);

