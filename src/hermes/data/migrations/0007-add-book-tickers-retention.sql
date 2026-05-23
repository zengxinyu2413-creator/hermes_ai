-- migration: 0007-add-book-tickers-retention
-- author: Hermes Project
-- date: 2026-05-21
-- description: Add automatic retention policy to book_tickers.
--              Chunks older than 30 days are dropped automatically.
--              30-day retention is specified in schema §2 (data lifecycle) and §6.6
--              (retention policy). Data beyond this window has no operational value
--              for the intended intraday / short-horizon strategies.
-- depends-on: 0006-add-book-tickers-compression
-- estimated-duration: <5 seconds
-- requires-downtime: no
-- destructive: no (only attaches a background job; existing data is untouched at apply time)


SELECT add_retention_policy('book_tickers', INTERVAL '30 days');

