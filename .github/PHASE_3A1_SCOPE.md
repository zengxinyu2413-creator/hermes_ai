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
| 9 | trades table: 0007-create-trades migration + rollback |
| 10 | trades hypertable: 0008-create-trades-hypertable migration + rollback |
| 11 | trades compression: 0009-add-trades-compression migration + rollback + PROGRESS.md update |

## Principles

- **Three-step split per table**: each table is split into three migrations —
  `create-<table>` → `create-<table>-hypertable` → `add-<table>-compression`.
  Rationale: rollbacks are scoped; compression can be disabled without dropping
  the hypertable; hypertable promotion can be re-run independently.

- **Rollback without CASCADE**: `step.rollback` never uses `DROP ... CASCADE`.
  Drop only the object created in that specific step. Prevents accidental
  destruction of dependent objects when rolling back a single migration.

- **No retention policy**: all tables retain data permanently. No
  `add_retention_policy` calls anywhere in this phase.
