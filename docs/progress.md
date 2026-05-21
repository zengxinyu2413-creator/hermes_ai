# Hermes AI v6 — Phase 3.A.1 进度

Phase 3.A.1:数据层 migration 工具链与建表。
三张数据表(klines / book_tickers / trades)各自完成建表 / hypertable /
压缩 / retention(klines 无 retention)的 yoyo migration。
所有 migration 仅经语法验证(docker exec psql,BEGIN...ROLLBACK),未真 apply。

| # | 内容 | migration | commit | 状态 |
|---|------|-----------|--------|------|
| 1 | deps: yoyo-migrations + psycopg3 | — | efb5f70 | ✅ |
| 2 | infra: yoyo.ini + migrate.sh | — | 573d08a | ✅ |
| 3 | klines 建表 | 0001 | 3b0d233 | ✅ |
| 4 | klines hypertable | 0002 | 4d93229 | ✅ |
| 5 | klines 压缩 | 0003 | d915a75 | ✅ |
| 6 | book_tickers 建表 | 0004 | c3c01b9 | ✅ |
| 7 | book_tickers hypertable | 0005 | ec70551 | ✅ |
| 8 | book_tickers 压缩 | 0006 | 8e59be9 | ✅ |
| 9 | book_tickers retention | 0007 | 5cb7083 | ✅ |
| 10 | trades 建表 | 0008 | 7f78070 | ✅ |
| 11 | trades hypertable | 0009 | 6310b5c | ✅ |
| 12 | trades 压缩 | 0010 | 5a7347d | ✅ |
| 13 | trades retention + progress.md | 0011 | (this commit) | ✅ |
