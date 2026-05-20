# Hermes AI v6 — Project Status

**Last Updated:** 2026-05-20 (UTC)

## Current Phase
**Phase 3 — TimescaleDB Write Layer** (just started)

## Completed Phases
- Phase 1: Project skeleton, repo, Python 3.11.15 venv
- Phase 2: Binance Spot REST + WebSocket clients
  - 2.A-C: contracts, signing, credentials (Mainnet/Testnet/Demo)
  - 2.D.3-6: WS skeleton -> parsing -> read loop -> reconnect -> keepalive -> metrics
  - All unit tests green. src/hermes/exchanges/ FROZEN.

## In Progress (Phase 3.A — Infrastructure)
- Docker Engine 29.5.1 + Compose v5.1.3 installed
- TimescaleDB 2.27.1 on PostgreSQL 16.14 in container hermes-tsdb
  - Port: 127.0.0.1:5432 (localhost only)
  - Volume: hermes_tsdb_data (named)
  - Resource cap: 1.5GB RAM / 1.5 CPU
  - Credentials: ~/hermes/infra/.env (600, gitignored)
- TimescaleDB extension verified working (hypertable smoke test passed)

## Blocked
None.

## Next 3 Atomic Tasks (Phase 3.A continuation)
1. Schema design draft: klines, book_tickers, trades hypertables.
   Decisions needed: chunk_time_interval, compression policy, retention window.
2. Migration tooling decision: raw SQL files + custom runner, or yoyo?
   Constraint from handoff doc: NO SQLAlchemy ORM.
3. src/hermes/data/ skeleton: connection pool config + first migration.

## Architectural Constraints (do not violate)
- Prices/volumes: Decimal only, never float
- DB: raw psycopg3 + TypedDict/dataclass, NO SQLAlchemy ORM
- NUMERIC(18,8) <-> Python Decimal
- Test fixtures: must roll back transactions
- src/hermes/exchanges/ is FROZEN — Phase 3 does not modify it
- Migrations never run automatically (even on testnet)

## Stack
- OS: Ubuntu 24.04.4 LTS, kernel 6.8
- Python: 3.11.15 (venv at ~/hermes/venv)
- Host: Vultr Tokyo, 4GB / 2 vCPU, 94GB disk
