-- migration: 0005-create-book-tickers-hypertable (rollback)
-- description: Roll back the hypertable conversion. NOTE: create_hypertable() has no
--              inverse, so the only path is DROP TABLE + recreate as plain table. This
--              is broader than 0005's forward change — it also destroys all rows and
--              resets book_tickers to its 0004 (plain-table) state. Do NOT run this rollback
--              if you need to preserve data. No CASCADE needed (confirmed: no dependent objects
--              exist at this migration stage).
-- destructive: YES (irreversible data loss for any rows in book_tickers)
-- pre-check: confirm no application writers are running against book_tickers before rollback

BEGIN;

DROP TABLE IF EXISTS book_tickers;

CREATE TABLE book_tickers (
    symbol       TEXT          NOT NULL,
    received_at  TIMESTAMPTZ   NOT NULL,
    bid_price    NUMERIC(18,8) NOT NULL,
    bid_qty      NUMERIC(18,8) NOT NULL,
    ask_price    NUMERIC(18,8) NOT NULL,
    ask_qty      NUMERIC(18,8) NOT NULL,
    PRIMARY KEY (symbol, received_at)
);

COMMIT;
