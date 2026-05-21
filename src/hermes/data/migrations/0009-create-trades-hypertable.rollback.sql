-- migration: 0009-create-trades-hypertable (rollback)
-- description: Roll back the hypertable conversion. NOTE: create_hypertable() has no
--              inverse, so the only path is DROP TABLE + recreate as plain table.
--              This is broader than 0009's forward change — it also destroys all rows
--              and resets trades to its 0008 (plain-table) state. Do NOT run this
--              rollback if you need to preserve data. No CASCADE needed (confirmed:
--              no dependent objects exist at this migration stage).
-- destructive: YES (irreversible data loss for any rows in trades)
-- pre-check: confirm no application writers are running against trades before rollback

BEGIN;

DROP TABLE IF EXISTS trades;

CREATE TABLE trades (
    symbol          TEXT          NOT NULL,
    trade_id        BIGINT        NOT NULL,
    trade_time      TIMESTAMPTZ   NOT NULL,
    price           NUMERIC(18,8) NOT NULL,
    qty             NUMERIC(18,8) NOT NULL,
    is_buyer_maker  BOOLEAN       NOT NULL,
    PRIMARY KEY (symbol, trade_id, trade_time)
);

COMMIT;
