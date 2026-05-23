-- migration: 0001-create-klines
-- author: Hermes Project
-- date: 2026-05-21
-- description: Create klines plain table. No hypertable/compression here —
--              those land in 0002+ migrations per the rule
--              "one migration = one rollback-able change".
-- depends-on: (none)
-- estimated-duration: <5 seconds
-- requires-downtime: no
-- destructive: no


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

