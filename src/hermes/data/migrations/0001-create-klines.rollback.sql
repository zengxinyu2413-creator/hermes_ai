-- migration: 0001-create-klines (rollback)
-- description: Drop klines plain table and all its data.
-- destructive: YES (irreversible data loss; klines is 永久保留 in production)
-- pre-check: confirm no application writers are running against klines before rollback

BEGIN;

DROP TABLE IF EXISTS klines;

COMMIT;
