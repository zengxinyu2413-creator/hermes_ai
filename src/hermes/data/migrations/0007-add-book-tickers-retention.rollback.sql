-- migration: 0007-add-book-tickers-retention (rollback)
-- description: Remove the automatic retention policy from book_tickers.
--              After removal, chunks older than 30 days will no longer be dropped
--              automatically. Existing data is fully preserved; only the background
--              job that enforced the drop schedule is removed.
-- destructive: no (rollback does not drop any data; chunks that have already been
--              dropped by the policy before rollback cannot be recovered, but the
--              rollback operation itself discards no rows)

BEGIN;

SELECT remove_retention_policy('book_tickers', if_exists => true);

COMMIT;
