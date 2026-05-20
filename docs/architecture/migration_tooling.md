# Migration Tooling — Phase 3.A.0

> **Status**: Design document. No migrations written yet.
> **Phase**: 3.A.0 (Discovery + Decisions)
> **Scope**: yoyo-migrations 选型理由、目录结构、命名约定、SQL 文件规范、rollback 策略、CI 集成、运维流程。
> **Companions**: `timescaledb_schema.md` (schema 内容),`data_layer.md` (Python 侧 writer 衔接)。

---

## 1. 范围与目标

本文档定义 Phase 3 持久化层的 **DDL 部署机制**:

- 工具选型(yoyo-migrations)的理由与备选对比
- migration 目录结构与文件命名约定
- 每个 migration 文件的内容规范(up / down 模板)
- 配置文件(`yoyo.ini`)与环境变量约定
- Rollback 策略(开发期 + 灾难恢复)
- CI 集成方式
- 运维应用流程(testnet / mainnet 草拟)

**不解决**(留给后续):

- 具体的 migration SQL 文件 → Phase 3.A.1(基于 `timescaledb_schema.md` 写实际的 `0001-create-klines.sql` 等)
- 运行 yoyo 的封装脚本(`scripts/migrate.sh`)→ Phase 3.A.1
- mainnet runbook → Phase 5+ 的运维文档
- 备份恢复策略 → `docs/operations/`
- 数据迁移(非 schema 的,如 `UPDATE` 修复历史数据)→ 视需求定,本文档默认只覆盖 schema migration

---

## 2. 工具选型对比

### 2.1 候选

| 维度 | yoyo-migrations | alembic-sql 模式 | 自写 runner |
|---|---|---|---|
| 学习成本 | 极低(1 个 CLI 命令) | 中等(SQLAlchemy 生态心智负担) | 极高 |
| ORM 耦合 | 无 | alembic 本质给 ORM 用,sql-only 是边缘用法 | 无 |
| up / down 表达 | `up.sql` / `down.sql` 双文件,显式直观 | `env.py` + Python 类,要装样子 | 自己定 |
| Migration 状态表 | `_yoyo_migration` | `alembic_version` | 自己建 + 维护 |
| TimescaleDB DDL 兼容 | 原生 SQL,完全兼容 | 同(sql 模式) | 同 |
| 社区/维护 | 活跃但小众 | 大而活跃 | — |
| 复杂度成本 | 1 个 pip 依赖 | 装 SQLAlchemy + alembic 全家桶 | 自维护风险高 |
| 与 CLAUDE.md 约束的契合 | ✅(纯 SQL,无 ORM) | ⚠️(易引入 SQLAlchemy 漂移) | ✅(但不必要重复造轮子) |

### 2.2 决策:yoyo-migrations

理由:

- **零 ORM 污染**。CLAUDE.md 明确"Phase 3 不用 SQLAlchemy ORM,只用 raw psycopg3 + TypedDict/dataclass"。yoyo 不引入任何 ORM 代码。
- **TimescaleDB 友好**。yoyo 把整个 `.sql` 文件原样喂给 PG,`create_hypertable()` / `add_compression_policy()` 这些函数调用 100% 兼容。
- **轻量**:1 个 pip 依赖,1 个 CLI 命令(`yoyo apply` / `yoyo rollback`)。
- **up/down 双文件**:rollback 写在独立文件里,review 时 diff 清晰。

否决备选:

- **alembic-sql 模式**:虽然 sql-only 路径技术上可行,但 alembic 的 `env.py` 装样子代码冗余,且 alembic 文档/示例 99% 是 ORM 场景,排错时社区资源帮不上忙。
- **自写 runner**:与"代码加法"成本相比,yoyo 带来的依赖成本可忽略。Migration 状态表、并发锁、断点恢复都已经在 yoyo 里做好,自写要花数十小时。

### 2.3 版本约束(预告)

具体 `yoyo-migrations` pin 到的版本号留到 Phase 3.A.1 加入 `pyproject.toml` 时定。**本文档不固化版本**。

---

## 3. 目录结构

```
src/hermes/data/migrations/
├── __init__.py                          # 空,保持 Python package 形态(便于 pytest discovery)
├── yoyo.ini                             # yoyo 配置(non-secret)
├── 0001-create-klines.sql               # up
├── 0001-create-klines.rollback.sql      # down
├── 0002-create-book-tickers.sql
├── 0002-create-book-tickers.rollback.sql
├── 0003-create-trades.sql
└── 0003-create-trades.rollback.sql
```

### 3.1 设计决定

- **migration 文件就在 `src/hermes/data/migrations/` 里**,与 Python 数据层在同一棵子树下。便于:
  - `pyproject.toml` 的 package_data 配置一次性把 migration 打包进 wheel(未来分发)
  - 开发者 IDE 里跳转方便
  - migration 与 `models.py` / `writers/*` 一起做 PR review

- **`__init__.py` 保留为空**:yoyo 不需要 import,但保留 `__init__.py` 让 pytest 在递归扫描时不抱怨。

- **不使用日期戳前缀**(如 `20260520-create.sql`):多人/多分支协作时数字递增更可控,日期戳易撞车。

### 3.2 不要做的事

- ❌ 不把 migration 散落到 `migrations/` 顶层目录(项目根)—— 与代码远离,易遗忘
- ❌ 不混入数据 migration(`INSERT` 历史修复)与 schema migration —— 真有需要时单独开 `0NNN-data-fix-<desc>.sql` 并在头注释里标 `KIND: data` 与 schema 区分

---

## 4. 命名约定

### 4.1 格式

```
NNNN-<verb>-<entity>[-<qualifier>].sql
NNNN-<verb>-<entity>[-<qualifier>].rollback.sql
```

### 4.2 各字段约束

| 字段 | 约束 | 示例 |
|---|---|---|
| `NNNN` | 4 位补零数字,严格递增,**不允许 gap**(被 squash 的占位也保留空文件并 comment-only) | `0001`, `0042` |
| `<verb>` | 小写动词,kebab-case;含义清晰 | `create`, `alter`, `drop`, `add-index`, `set-policy`, `data-fix` |
| `<entity>` | 单数,与 dataclass 命名一致(如 `kline`,非 `klines`)。表名复数但 migration 文件用单数,以避免歧义 | `kline`, `book-ticker`, `trade` |
| `<qualifier>` | 可选,描述具体改动 | `add-vwap`, `partition-by-symbol` |

### 4.3 示例

```
0001-create-klines.sql                  ← create 动词 + 复数表名习惯放在文件名时按 dataclass 单数,但 entity 表的内容是复数表名
0002-create-book-tickers.sql            ← 同上
0003-create-trades.sql                  ← 同上
0042-alter-kline-add-vwap-column.sql    ← 加列示例(假想)
0050-add-index-trades-time-symbol.sql   ← 加索引示例
```

⚠️ **关于复数/单数的妥协**:严格按"entity 单数"原则,这三个文件应叫 `create-kline.sql` / `create-book-ticker.sql` / `create-trade.sql`。**但**它们创建的表名是复数,文件名跟表名对齐更利于搜索(`grep -r klines src/hermes/data/migrations`)。**本项目最终采用"文件名与表名一致(复数)"**,与"entity 单数"原则破例 —— 这是显式约定,不是疏忽。

### 4.4 禁止

- 日期戳前缀 / 时间戳
- 大写字母 / 下划线(用 kebab-case)
- 长描述(超 60 字符);详细描述写进 SQL 注释
- 中文 / 非 ASCII 字符
- 数字回头跳(`0001` 之后跳 `0003` 跳过 `0002`)—— 即使作废也保留 placeholder

---

## 5. Migration 文件内容规范

### 5.1 up 文件模板

```sql
-- migration: 0001-create-klines
-- author: <name | AI session id>
-- date: 2026-XX-XX
-- description: Create klines hypertable with compression policy (>30d).
--              No retention policy (永久保留 per timescaledb_schema.md §5.6).
-- depends-on: (none)
-- estimated-duration: <5 seconds
-- requires-downtime: no
-- destructive: no

BEGIN;

CREATE TABLE klines (
    symbol           TEXT          NOT NULL,
    interval         TEXT          NOT NULL,
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

SELECT create_hypertable(
    'klines',
    'open_time',
    chunk_time_interval => INTERVAL '7 days'
);

ALTER TABLE klines SET (
    timescaledb.compress,
    timescaledb.compress_orderby = 'open_time DESC',
    timescaledb.compress_segmentby = 'symbol, interval'
);

SELECT add_compression_policy('klines', INTERVAL '30 days');

COMMIT;
```

### 5.2 down 文件模板

```sql
-- migration: 0001-create-klines (rollback)
-- description: Drop klines hypertable and all its data.
-- destructive: YES (irreversible data loss; klines is 永久保留 in production)
-- pre-check: ensure pg_dump backup exists if running on data-bearing instance

BEGIN;

-- yoyo will auto-stop the compression policy job on table drop, but explicit is safer
SELECT remove_compression_policy('klines', if_exists => true);

DROP TABLE IF EXISTS klines CASCADE;

COMMIT;
```

### 5.3 文件头 metadata 约束

每个 up 文件**必须**在头部带:

| 字段 | 必填? | 用途 |
|---|---|---|
| `migration:` | ✅ | 与文件名一致 |
| `author:` | ✅ | git blame 之外的快速归属 |
| `date:` | ✅ | 创建日期 |
| `description:` | ✅ | 一行说明本次改动 |
| `depends-on:` | ✅ | 依赖的前置 migration ID,或 `(none)` |
| `estimated-duration:` | ✅ | 经验估计,运维参考 |
| `requires-downtime:` | ✅ | `no` / `yes (reason)` |
| `destructive:` | ✅ | `no` / `yes` |

down 文件 metadata 简化但**必须**带 `destructive` 标记。

### 5.4 SQL 编写约束

- **强制 `BEGIN ... COMMIT` 包裹**:虽然 yoyo 默认每个 migration 自动一个事务,显式写让 SQL 文件单独执行(`psql -f`)也能正确事务化
- **TimescaleDB 函数允许在事务内**:`create_hypertable()` / `add_compression_policy()` 等都是 transaction-safe(2.x 起)
- **禁止裸 `DROP TABLE` 不带 `IF EXISTS`** —— rollback 文件里必须用 `IF EXISTS` 兜底
- **禁止跨表 join 在 migration 里**(数据 migration 例外,但要在 `kind: data` 头部声明)
- **禁止单文件多 schema 操作**(`CREATE TABLE A; CREATE TABLE B;` 不要写在一个 migration 里;每个 migration 一个清晰意图)

---

## 6. 配置:yoyo.ini

### 6.1 文件位置

`src/hermes/data/migrations/yoyo.ini`(与 migration SQL 同目录,便于 yoyo 默认发现)

### 6.2 内容(示意,Phase 3.A.1 写真实文件时定稿)

```ini
[DEFAULT]
sources = .
database = postgresql://%(TSDB_USER)s:%(TSDB_PASSWORD)s@%(TSDB_HOST)s:%(TSDB_PORT)s/%(TSDB_DB)s
batch_mode = on
verbosity = 2
post_create_paths =
```

### 6.3 关键配置项说明

| 字段 | 值 | 理由 |
|---|---|---|
| `sources` | `.` | 当前目录(yoyo.ini 所在目录) |
| `database` | 环境变量插值 | 不存明文密码 |
| `batch_mode` | `on` | 非交互模式,适合 CI / 脚本调用 |
| `verbosity` | `2` | INFO 级别;CI 里可用 `--verbosity 3` 拉到 DEBUG |

### 6.4 环境变量来源

- 来自 `~/hermes_ai/infra/.env`(已存在,见 `data_layer.md` §3.4)
- 字段:`TSDB_USER` / `TSDB_PASSWORD` / `TSDB_HOST` / `TSDB_PORT` / `TSDB_DB`
- 通过 `scripts/migrate.sh`(Phase 3.A.1 实现)做 `set -a; source .env; set +a` 后调用 yoyo

### 6.5 不要做的事

- ❌ 在 `yoyo.ini` 写明文密码
- ❌ 把 `yoyo.ini` 加进 `.gitignore`(它本身不敏感,要进 git)
- ❌ 把 `.env` 加进 git
- ❌ 在 CI 里把密码作为 plain text env 暴露 —— 用 GitHub Actions secrets

---

## 7. Rollback 策略

### 7.1 两层模型

**Layer A:Migration 内 rollback(yoyo 标准)**

- 命令:`yoyo rollback --revision <ID>` 回滚到指定 migration 之前的状态
- 适用:开发期发现 schema 错误、撤回最近一次 migration、testnet 数据库重置
- 单步 rollback:`yoyo rollback -n 1`(只回滚最新一个)

**Layer B:灾难恢复(超出 yoyo)**

- 工具:`pg_dump` / `pg_basebackup` + WAL replay
- 适用:数据损坏、灾难性 schema 错误已带数据、跨版本不兼容
- 流程:见 `docs/operations/`(Phase 5+ 单独文档,**本文档不固化**)

### 7.2 Destructive Rollback 红线

任何 `DROP TABLE` / `TRUNCATE` 类 rollback,在不同环境的执行约束:

| 环境 | 允许直接 `yoyo rollback`? | 前置要求 |
|---|---|---|
| 开发 / 本地 | ✅ | 无 |
| Testnet | ✅ | log 记录 |
| Mainnet | ❌ | 必须先 `pg_dump` 备份,运维人工执行;**不允许 CI 自动 rollback** |

### 7.3 Rollback SQL 的强制要求

- 每个 migration 必须有配套的 `.rollback.sql` —— **不允许只有 up 没有 down**
- 不可逆操作(如 `DROP COLUMN` 后数据已丢失)的 rollback SQL 可以是 "best effort",在 metadata 里明确标 `destructive: yes`,但**不允许空文件**
- CI lint 强制检查所有 up 都有配套 down(见 §9)

### 7.4 不要做的事

- ❌ rollback SQL 留空 / 写注释 "TODO: implement later"
- ❌ 一次回滚跨多个 migration 不做中间状态验证
- ❌ Mainnet 上未备份直接 rollback

---

## 8. 应用流程(运维 SOP)

### 8.1 开发 / Testnet 流程

```
1. git pull (确认 migration 文件已合入)
2. 停 writer (if running):见 data_layer.md §6 graceful shutdown
3. cd src/hermes/data/migrations
4. scripts/migrate.sh apply   # (Phase 3.A.1 实现的封装脚本)
   实际等价于:set -a; source ~/hermes_ai/infra/.env; set +a; yoyo apply
5. 验证:scripts/migrate.sh status (列出已应用的 migration)
6. 起 writer
7. Smoke test:insert 一条 → select 验证
```

### 8.2 Mainnet 流程(草拟,Phase 5+ 正式化)

```
1. 在 staging PG 复刻 mainnet schema,先跑 migration 验证(scripts/migrate.sh apply --dry-run 之后实跑)
2. pg_dump 全量备份 mainnet(`pg_dump -Fc hermes > hermes-pre-<migrationID>.dump`)
3. 通知 stakeholders 维护窗口开始
4. 停 production writer + dispatcher
5. yoyo apply (单步,不批量;每条 migration 跑完看 PG 状态再决定下一条)
6. 监控 5 分钟:pg_stat_activity / disk space / lock waits
7. 起 writer
8. 数据完整性 check:近 60s 应有新数据落 3 张表
9. 维护窗口关闭通告
```

⚠️ **Phase 3.A.0 不实现 mainnet runbook**。上文只是预告流程。真正落地到 Phase 5+ 时,会写专门的 `docs/operations/migration-runbook.md`。

### 8.3 紧急回滚(testnet)

```
1. 停 writer
2. scripts/migrate.sh rollback -n 1   # 回滚最新一个
3. 验证 schema 恢复:psql -d hermes -c "\dt"
4. 起 writer
```

### 8.4 不要做的事

- ❌ writer 还在跑时 apply migration(schema 变更涉及锁,会卡 writer)
- ❌ 不验证就 production deploy
- ❌ 跳过 status 检查直接 apply

---

## 9. CI 集成

### 9.1 PR 阶段(每次 push 触发)

**Lint 检查**(快,几秒):

1. **文件名格式校验**(简单 shell / Python 脚本):
```bash
   ls src/hermes/data/migrations/*.sql | \
     awk '!/^src\/hermes\/data\/migrations\/[0-9]{4}-[a-z0-9-]+(\.rollback)?\.sql$/ {print "BAD: "$0; exit 1}'
```
2. **up / down 配对校验**:每个 `NNNN-*.sql` 必须有对应的 `NNNN-*.rollback.sql`
3. **NNNN 不允许 gap**:简单数字递增校验
4. **metadata 头校验**:`grep` 强制 `migration:` / `description:` / `destructive:` 等字段存在
5. **`yoyo apply --dry-run`**:列出将执行的 migration(不真执行,需要起一个临时 PG 容器)

### 9.2 Integration 阶段(每次合 main 触发)

**Apply + Rollback 测试**(Phase 3.C 加,**不在 3.A.0 实现**):

1. 起临时 PG 16 + TimescaleDB 2.x 容器(GitHub Actions service container)
2. `yoyo apply` 全部 migration
3. 验证 schema:`\dt`、`\d klines` 等
4. `yoyo rollback` 全部
5. 验证表全部清空
6. `yoyo apply` 再次(测幂等性)

### 9.3 Phase 3.A.0 不固化的内容

- 具体 GitHub Actions YAML 文件 —— Phase 3.A.1 / 3.C 写实际 workflow 时定
- CI 容器镜像版本 pin
- secrets 注入方式细节(原则:用 GitHub Actions Secrets,**不写到 workflow 文件**)

---

## 10. 与 data_layer.md 的衔接

### 10.1 三者同步约束

每次 schema 变更涉及三个地方,**必须同步**:

1. **新 migration**(`src/hermes/data/migrations/NNNN-*.sql` + `.rollback.sql`)
2. **`models.py`** 里对应的 dataclass(`KlineRow` 等)
3. **`writers/*`** 里 INSERT SQL 模板

约束:

- 三处不一致是 bug —— 任一变更必须同 PR 改三处
- code review 时强制 reviewer 三处都看
- Phase 7+ 考虑 codegen 自动同步(从 PG schema 反向生成 dataclass + INSERT 模板),**当前不在范围**

### 10.2 测试期间的 migration 应用

- Integration test fixture(`data_layer.md` §8.3)在每次 test 开始前确保 schema 是最新的
- 实现方式:fixture 依赖一个 session-scoped fixture 跑 `yoyo apply`
- test 跑完不 rollback schema(下次 fixture 进入时已是最新状态)
- 具体实现在 Phase 3.C,本文档只声明约束

### 10.3 Writer 不感知 migration 状态

- Writer 启动时**不**检查 schema 版本
- 假定 migration 已经在 writer 启动前应用完毕(运维流程保证,见 §8.1)
- 若 writer 启动后遇到 schema 错位(`UndefinedColumn` 之类),立刻 CRITICAL log + 退出(不重试)

---

## 11. 不在本文档范围内

明确**不**在本文档解决:

- 具体的 `0001-create-klines.sql` 等 SQL 文件内容 → Phase 3.A.1
- `scripts/migrate.sh` 封装脚本 → Phase 3.A.1
- `pyproject.toml` 里的 `yoyo-migrations` 依赖声明 → Phase 3.A.1
- mainnet migration runbook → Phase 5+ `docs/operations/`
- 备份恢复策略(`pg_dump` / `pg_basebackup` / WAL) → `docs/operations/`
- 多环境(dev / staging / prod)config 管理 → Phase 4+
- Data migration(`UPDATE` 修复历史数据)细节策略 → 视需求,可能 Phase 3.D 或更晚
- Schema codegen(PG → dataclass 自动同步)→ Phase 7+

---

## 12. 未决问题清单

落地前(Phase 3.A.1 写第一个 migration 时)必须解决:

1. **`yoyo-migrations` 版本 pin**:`pyproject.toml` 里固定哪个版本号?Phase 3.A.1 装包时定。
2. **封装脚本语言**:`scripts/migrate.sh`(bash)还是 `scripts/migrate.py`(Python)?倾向 bash(无依赖、薄封装),但若需要 cross-platform 兼容(Windows 开发机),用 Python。当前 Linux-only 假设,bash 即可。
3. **CI 临时 PG 容器版本**:Phase 3.A.1 写 GitHub Actions 时,镜像选 `timescale/timescaledb:2.27.1-pg16`(与 prod 同)还是 `timescale/timescaledb-ha`?倾向同 prod。
4. **Metadata 校验的实现**:CI 里用纯 `grep` / `awk` 还是写一个 Python script?简单的话 shell 即可。
5. **`yoyo.ini` 的 `database` 字段是否真的支持环境变量插值**:需要回查 yoyo 文档确认 `%(VAR)s` 语法在 ini 文件里能否使用,或者改用命令行参数 `yoyo apply --database "$DATABASE_URL"` 传入。Phase 3.A.1 实测时验证。
6. **Migration apply 在 integration test 里的执行点**:`pytest_asyncio` session fixture 还是 conftest.py module-level?见 `data_layer.md` §8.3 关联讨论,Phase 3.C 实现时定。
7. **Squash 策略**:多年后 migration 文件 >100 个,是否做 squash?当前 v6 不考虑,Phase 11+ 评估。

---

**End of document.**