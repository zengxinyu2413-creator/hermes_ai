-- migration: 0002-create-klines-hypertable (rollback)
-- description: Roll back the hypertable conversion. NOTE: create_hypertable() has no
--              inverse, so the only path is DROP TABLE + recreate as plain table. This
--              is broader than 0002's forward change — it also destroys all rows and
--              resets klines to its 0001 (plain-table) state. Do NOT run this rollback
--              if you need to preserve data. No CASCADE needed (confirmed by local test).
-- destructive: YES (irreversible data loss for any rows in klines)
-- pre-check: confirm no application writers are running against klines before rollback

BEGIN;

DROP TABLE IF EXISTS klines;

CREATE TABLE klines (
    symbol           TEXT          NOT NULL,
    interval         TEXT          NOT NULL, -- PostgreSQL non-reserved keyword; valid as column name
    open_time        TIMESTAMPTZ   NOT NULL,
    close_time       TIMESTAMPTZ   NOT NULL,
    open             NUMERIC(18,8) NOT NULL,
    high             NUMERIC(18,8) NOT NULL,
    low              NUMERIC(18,8) NOT NULL,
    close            NUMERIC(18,8) NOT NULL,
    volume           NUMERIC(18,8) NOT NULL,
    quote_volume     NUMERIC(18,8) NOT NULL,
    trades           INTEGER       NOT NULL,
    taker_buy_base   NUMERIC(18,8) NOT NULL,
    taker_buy_quote  NUMERIC(18,8) NOT NULL,
    is_closed        BOOLEAN       NOT NULL,
    PRIMARY KEY (symbol, interval, open_time)
);

COMMIT;
