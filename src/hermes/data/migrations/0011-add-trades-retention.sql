-- migration: 0011-add-trades-retention
-- author: Hermes Project
-- date: 2026-05-21
-- description: Add retention policy to trades. Chunks older than 30 days are
--              dropped automatically. This is the final migration of Phase 3.A.1.
-- depends-on: 0010-add-trades-compression
-- estimated-duration: <5 seconds
-- requires-downtime: no
-- destructive: no (policy only; no existing data is dropped at apply time)


SELECT add_retention_policy('trades', INTERVAL '30 days');

