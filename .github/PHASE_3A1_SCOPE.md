# Phase 3.A.1 — Infrastructure Migrations Scope

## Commit Breakdown

### Completed

| # | Commit | Description |
|---|--------|-------------|
| 1 | efb5f70 | deps: add yoyo-migrations + psycopg3 to pyproject.toml |
| 2 | 573d08a | toolchain: add yoyo.ini and migrate.sh wrapper |
| 3 | 3b0d233 | klines table: 0001-create-klines migration + rollback |
| 4 | 4d93229 | klines hypertable: 0002-create-klines-hypertable migration + rollback |
| 5 | d915a75 | klines compression: 0003-add-klines-compression migration + rollback |

### Pending

| # | Description |
|---|-------------|
| 6 | book_tickers table: 0004-create-book-tickers migration + rollback |
| 7 | book_tickers hypertable: 0005-create-book-tickers-hypertable migration + rollback |
| 8 | book_tickers compression: 0006-add-book-tickers-compression migration + rollback |
| 9 | book_tickers retention: 0007-add-book-tickers-retention migration + rollback |
| 10 | trades table: 0008-create-trades migration + rollback |
| 11 | trades hypertable: 0009-create-trades-hypertable migration + rollback |
| 12 | trades compression: 0010-add-trades-compression migration + rollback |
| 13 | trades retention: 0011-add-trades-retention migration + rollback + PROGRESS.md update |

## Principles

- **Per-table split**: klines splits into 3 migrations
  (table → hypertable → compression). book_tickers and trades split into 4
  (table → hypertable → compression → retention).
  Rationale: each migration = one rollback-able change; retention is a
  separate, independently rollback-able step.

- **Rollback without CASCADE**: `step.rollback` never uses `DROP ... CASCADE`.
  Drop only the object created in that specific step. Prevents accidental
  destruction of dependent objects when rolling back a single migration.

- **Retention**: klines retained permanently (no retention policy).
  book_tickers and trades use 30-day retention (`add_retention_policy`, 30 days),
  per timescaledb_schema.md §2 / §6.6.
