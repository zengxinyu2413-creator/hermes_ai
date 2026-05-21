-- migration: 0008-create-trades
-- author: Hermes Project
-- date: 2026-05-21
-- description: Create trades plain table. No hypertable/compression here —
--              those land in 0009+ migrations per the rule
--              "one migration = one rollback-able change".
--              Primary key is (symbol, trade_id, trade_time): logically (symbol, trade_id)
--              is sufficient because Binance trade_id is globally monotone-unique, but
--              TimescaleDB requires the partition column (trade_time) to be part of the PK
--              (§7.3). trade_time is a partitioning aid; trade_id is the true logical key.
-- depends-on: (none)
-- estimated-duration: <5 seconds
-- requires-downtime: no
-- destructive: no

BEGIN;

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
