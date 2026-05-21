-- migration: 0004-create-book-tickers
-- author: Hermes Project
-- date: 2026-05-21
-- description: Create book_tickers plain table. No hypertable/compression here —
--              those land in 0005+ migrations per the rule
--              "one migration = one rollback-able change".
-- depends-on: (none)
-- estimated-duration: <5 seconds
-- requires-downtime: no
-- destructive: no

BEGIN;

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
