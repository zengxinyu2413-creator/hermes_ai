-- migration: 0008-create-trades (rollback)
-- description: Drop trades plain table and all its data.
-- destructive: YES (irreversible data loss; trades has 30-day retention in production)
-- pre-check: confirm no application writers are running against trades before rollback


DROP TABLE IF EXISTS trades;

