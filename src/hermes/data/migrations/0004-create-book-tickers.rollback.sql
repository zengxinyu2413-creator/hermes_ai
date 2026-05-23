-- migration: 0004-create-book-tickers (rollback)
-- description: Drop book_tickers plain table and all its data.
-- destructive: YES (irreversible data loss; book_tickers has 30-day retention in production)
-- pre-check: confirm no application writers are running against book_tickers before rollback


DROP TABLE IF EXISTS book_tickers;

