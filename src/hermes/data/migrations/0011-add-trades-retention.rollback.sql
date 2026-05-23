-- migration: 0011-add-trades-retention (rollback)
-- description: Remove the trades retention policy. No data is restored
--              (retention drops are irreversible); this only stops future drops.
-- destructive: no


SELECT remove_retention_policy('trades', if_exists => true);

