# Phase 3.A.1 — Migration Tooling Implementation SCOPE

> **Phase**: 3.A.1
> **Author**: Designed at end of 3.A.0 session (2026-05-20)
> **Predecessor**: Phase 3.A.0 (Discovery + Decisions, 3 design docs committed)
> **Successor**: Phase 3.B (Ingestion lifecycle) or 3.C (Async writer implementation)
> **Working style**: 每个 commit 用户点 "go" 才执行;人审 + go-then-commit;顺序串行,不并行多文件。

---

## 1. 上下文

### 1.1 Phase 3.A.0 留下什么

Phase 3.A.0 在 main 分支留下三份设计文档(纯文档,0 代码,0 表):

| Commit | 文档 | 行数 |
|---|---|---|
| `79f1faa` | `docs/architecture/timescaledb_schema.md` | 397 |
| `6c5ea2a` | `docs/architecture/data_layer.md` | 565 |
| `dc7fff7` | `docs/architecture/migration_tooling.md` | 460 |

三份文档共**17 条未决问题**,Phase 3.A.1 需要解决其中 **5 条阻塞项**(见 §6),其余推到 3.C。

### 1.2 路线图中的位置

```
Phase 3.A.0 (DONE)  ─── 设计文档 ────► 知道要怎么做
   │
   ▼
Phase 3.A.1 (THIS) ─── DDL 落地 ────► 数据库真的有三张表
   │                                  yoyo 工具链可跑
   │                                  封装脚本可用
   │
   ▼
Phase 3.B  ────── Ingestion lifecycle ── WsClient 启动/优雅停机协议
   │
   ▼
Phase 3.C  ────── Python 写入代码 ────── pool / models / converters / writers
   │
   ▼
Phase 3.D  ────── Integration + E2E test
```

**Phase 3.A.1 的边界明确**:DDL 真正应用到数据库 + 工具链就绪,但 **`src/hermes/data/` 里除了 `__init__.py` 和 `migrations/` 目录之外不写任何 Python 代码**。

---

## 2. 核心目标

把 `timescaledb_schema.md` 设计的三张 hypertable **真正建到 `hermes-tsdb` 容器里**,通过 yoyo-migrations 管理,有完整的 up/down 路径,有封装脚本,有 lint。

Phase 3.A.1 跑完时:

- ✅ `hermes-tsdb` 容器里 `\dt` 看得到 `klines` / `book_tickers` / `trades` 三张表
- ✅ 三张表都已配 hypertable + compression policy + retention(klines 永久)
- ✅ `_yoyo_migration` 状态表记录 3 条已应用 migration
- ✅ `scripts/migrate.sh apply` / `rollback` / `status` 三个命令都能跑
- ✅ `scripts/lint-migrations.sh` 通过(文件名格式 + up/down 配对校验)
- ✅ `pyproject.toml` 含 `yoyo-migrations` + psycopg3 依赖,无 dependency conflict
- ✅ 主流程跑过完整一遍:apply → rollback → apply(测幂等)→ smoke test → rollback
- ✅ `PROGRESS.md` 更新到 3.A.1 complete

---

## 3. 范围内(做)

### 3.1 依赖管理

- `pyproject.toml` 加 `yoyo-migrations` 依赖
- 同时加 `psycopg[binary]` + `psycopg-pool`(为 3.C 铺路)
- 解决 dependency conflict(若有)

### 3.2 工具链文件

- `src/hermes/data/migrations/yoyo.ini`(配置)
- `src/hermes/data/migrations/__init__.py`(空,保持 package 形态)
- `scripts/migrate.sh`(封装脚本,读 `.env` 注入环境变量 → 调 yoyo)
- `scripts/lint-migrations.sh`(文件名 + 配对校验)

### 3.3 Migration SQL 文件(3 对)

- `0001-create-klines.sql` + `0001-create-klines.rollback.sql`
- `0002-create-book-tickers.sql` + `0002-create-book-tickers.rollback.sql`
- `0003-create-trades.sql` + `0003-create-trades.rollback.sql`

每个 up 文件严格按 `migration_tooling.md` §5.1 模板,带 metadata 头 + `BEGIN/COMMIT` 包裹。

每个 down 文件按 §5.2 模板,带 `destructive` 标记。

### 3.4 真实执行验证

按下面顺序在 `hermes-tsdb` 容器跑通:

1. `scripts/migrate.sh apply` —— 三张表全建
2. `psql` 进容器验证 `\d klines` / `\d book_tickers` / `\d trades`
3. `SELECT * FROM timescaledb_information.hypertables` 验证三张表都是 hypertable
4. `SELECT * FROM timescaledb_information.jobs` 验证 compression policy 注册成功
5. `SELECT * FROM timescaledb_information.policies` 验证 retention(klines 没有 retention job,book_tickers / trades 有)
6. **smoke test**:每张表 INSERT 1 条 → SELECT 1 条 → 确认 NUMERIC(18,8) 精度正确(`Decimal("123.45678901")` 入库后取出仍是同样字符串)→ DELETE 测试数据
7. `scripts/migrate.sh rollback -n 3` —— 三张表全删
8. 验证 `\dt` 空
9. `scripts/migrate.sh apply` 再跑一次 —— 幂等性 + 重建路径 OK
10. **最终状态**:三张表存在、空表、policy 注册、ready for 3.C

### 3.5 文档维护

- `PROGRESS.md` 加一节 "Phase 3.A.1 complete",列出本阶段的 commit hash 和验证结果
- 不修改 `CHANGELOG.md`(那是用户级 changelog,内部 phase 推进不记)

---

## 4. 范围外(不做)

### 4.1 代码层面

- ❌ **不写 `src/hermes/data/pool.py`**(Phase 3.C)
- ❌ **不写 `src/hermes/data/models.py`**(3.C)
- ❌ **不写 `src/hermes/data/converters.py`**(3.C)
- ❌ **不写 `src/hermes/data/writers/*.py`**(3.C)
- ❌ **不接 `BinanceWsClient.stream()`** 灌真实数据(3.B/3.C)
- ❌ **不动 `src/hermes/exchanges/`**(FROZEN,Phase 2 已封)
- ❌ **不动 `src/hermes/{regime,strategies,risk,execution,orchestrator,monitoring,backtest}/`** 任何 stub

### 4.2 测试层面

- ❌ **不写 integration test**(需要 pool fixture,pool 需要 pool.py;3.C/3.D)
- ❌ **不写 unit test**(converters 还没有,没东西测;3.C)
- ❌ smoke test 只在终端手跑,**不进 pytest**(避免引入 fixture 依赖)

### 4.3 CI 层面

- ❌ **不动 `.github/workflows/*.yml`**(本阶段的 lint 是本地脚本,workflow 加 yoyo apply --dry-run 等 CI job 留到 3.C)
- ❌ **不实现** `migration_tooling.md` §9.2 的"apply + rollback 测试"job

### 4.4 运维层面

- ❌ **不写 mainnet runbook**(Phase 5+)
- ❌ **不实现** pg_dump / pg_basebackup 备份自动化
- ❌ **不做** secrets 注入到 GitHub Actions

---

## 5. Pre-flight checklist(写第一行代码前必查)

### 5.1 Step 0 — 回查 `BookTicker` dataclass

```bash
cat src/hermes/exchanges/binance_contracts.py | grep -A 25 "class BookTicker"
```

期望结果分支:

| 结果 | 行动 |
|---|---|
| **a. 含 `update_id`** | 直接用,SQL 文件按 `timescaledb_schema.md` §6.3 主键设计 |
| **b. 不含,但原始 payload 含 `u`** | SQL 文件不变(`update_id BIGINT NOT NULL`),Phase 3.C 写入层从 raw payload 取。在 3.A.1 期间 INSERT smoke test 时,update_id 手填一个合法 BIGINT |
| **c. 都没有** | 阻塞,先改 `timescaledb_schema.md` §6,主键退化为 `(symbol, received_at, bid_price, ask_price)`,然后再继续 3.A.1 |

### 5.2 Step 1 — yoyo 实际行为验证

在 venv 里:

```bash
pip install yoyo-migrations
yoyo --version
yoyo --help
```

**关键未决**:`yoyo.ini` 是否支持 `%(VAR)s` 环境变量插值?(详见 `migration_tooling.md` §12.5)实测:

```bash
# 写一个最小 yoyo.ini 用 %(TSDB_USER)s,跑一次 apply 看是否报错
```

| 结果 | 行动 |
|---|---|
| **a. 支持插值** | yoyo.ini 用 §6.2 写法 |
| **b. 不支持插值** | 改用命令行参数:`yoyo apply --database "$DATABASE_URL"`,封装脚本 `migrate.sh` 里组装完整 DSN 传入 |

### 5.3 Step 2 — 包管理器确认

```bash
ls pyproject.toml uv.lock poetry.lock 2>/dev/null
cat pyproject.toml | head -30
```

确认当前用 uv / poetry / 还是 plain pip,影响第 1 个 commit 怎么改。

### 5.4 Step 3 — 容器健康检查

```bash
docker ps --filter name=hermes-tsdb --format "{{.Status}}"
docker exec hermes-tsdb pg_isready -U hermes -d hermes
```

预期:`Up X (healthy)` + `accepting connections`。

如果容器掉了,先 `cd ~/hermes_ai/infra && docker compose up -d` 起回来,确认 healthy 再继续。

### 5.5 Step 4 — 一个 migration 端到端走通,再批量

写完 0001(klines) 立刻 apply 一次,验证 hypertable + compression policy 创建成功,再继续写 0002 / 0003。**禁止一次性写三个 migration 再 apply** —— 出错时 bisect 困难。

---

## 6. 必须在 3.A.1 解决的 5 条未决问题

从 3.A.0 三份文档的「未决问题」清单提取,**3.A.1 范围内必须给答案**:

| # | 问题 | 来源 | 解决时机 |
|---|---|---|---|
| 1 | `BookTicker.update_id` 来源 | schema §12.1, data_layer §4.3 | Step 0 |
| 2 | `yoyo-migrations` pin 哪个版本 | migration §12.1 | 第 1 个 commit 前 |
| 3 | `yoyo.ini` 环境变量插值是否支持 | migration §12.5 | Step 1 |
| 4 | trades 主键的 hypertable 约束验证 | schema §12.5 | 0003 apply 时立刻知道 |
| 5 | 封装脚本语言(bash vs Python) | migration §12.2 | 第 2 个 commit 前 |

其他 12 条留给 Phase 3.C 或更晚。

---

## 7. 工作粒度与 commit 序列

7 个 commit,顺序串行,每个之间用户点 "go" 才执行。预计 1.5-2 个会话(每会话 ~90 分钟)。

| # | Commit message | 包含文件 | 验证步骤 |
|---|---|---|---|
| 1 | `chore(deps): add yoyo-migrations + psycopg3 to pyproject.toml` | `pyproject.toml` + lockfile | `pip install -e .` 无冲突 |
| 2 | `infra(migrations): yoyo.ini and migrate.sh wrapper` | `src/hermes/data/migrations/yoyo.ini` + `src/hermes/data/migrations/__init__.py` + `scripts/migrate.sh` | `scripts/migrate.sh --help` 或 `status` 跑通 |
| 3 | `migrations: 0001 create klines hypertable` | `0001-create-klines.sql` + `.rollback.sql` | `apply` → `\d klines` → hypertable 验证 → `rollback` → `\dt` 空 → `apply` |
| 4 | `migrations: 0002 create book_tickers hypertable` | `0002-...` 双文件 | 同 #3 但针对 book_tickers + retention policy 验证 |
| 5 | `migrations: 0003 create trades hypertable` | `0003-...` 双文件 | 同 #3 但针对 trades + **主键约束验证** |
| 6 | `ci(migrations): file name + up/down pairing lint script` | `scripts/lint-migrations.sh` | 跑一次,所有现有 migration 通过 |
| 7 | `docs(progress): Phase 3.A.1 complete` | `PROGRESS.md` | git log 验证 7 个 commit + 三张表存在 |

每个 commit **独立 push**(参照 3.A.0 的做法,事故时不丢已 push 的部分)。

---

## 8. 风险与缓解

### 8.1 风险 R1:Dependency conflict

`yoyo-migrations` 可能与项目现有依赖冲突(尤其 SQLAlchemy 系列,但本项目应该没有)。

**缓解**:第 1 个 commit 前,先在临时 venv 跑:

```bash
python -m venv /tmp/yoyo-test-venv
/tmp/yoyo-test-venv/bin/pip install yoyo-migrations psycopg psycopg-pool
/tmp/yoyo-test-venv/bin/pip check
```

如有冲突,先在临时 venv 解决,再写进 `pyproject.toml`。

### 8.2 风险 R2:yoyo.ini 不支持环境变量插值

详见 §5.2。

**缓解**:Step 1 实测;不支持就 fallback 到命令行参数传入 DSN。

### 8.3 风险 R3:trades 主键 + hypertable 约束冲突

`timescaledb_schema.md` §7.3 推测 hypertable 强制要求 PK 包含时间分区列,所以设计为 `(symbol, trade_id, trade_time)`。但**没在容器里验证过**。

**缓解**:第 5 个 commit(0003) 写完立刻 apply,失败时:

- 错误信息明确说"必须包含 trade_time" → 当前设计正确,继续
- 错误信息说"不允许 trade_id 后跟 trade_time" → 调整列顺序为 `(symbol, trade_time, trade_id)`,改 schema 文档对应章节,然后继续
- 其他错误 → 停下来,记录,与用户讨论

### 8.4 风险 R4:Smoke test 时 NUMERIC(18,8) 精度异常

理论上 `psycopg3` 自动 Decimal ↔ NUMERIC,但 smoke test 时如果用 `psql` 输入,人手可能输入精度不足或多。

**缓解**:smoke test 用固定字符串 `'123.45678901'`(8 位小数恰好),验证 SELECT 返回值也是 `'123.45678901'`(不是 `'123.45678901000'` 也不是 `'123.456789'`)。如有偏差,记录,与用户讨论是否需要在 schema 加 `CHECK` 约束。

### 8.5 风险 R5:容器在 3.A.1 期间挂掉

`hermes-tsdb` 容器在 3.A.1 长时间使用过程中可能因 OOM / 磁盘满 / 其他原因挂掉。

**缓解**:每个 commit 验证前先 `docker ps` + `pg_isready` 确认容器健康(已纳入 §5.4 checklist)。

---

## 9. 完成定义(Done)

Phase 3.A.1 完成等于以下**全部**为真:

- [ ] `pyproject.toml` 含 `yoyo-migrations`, `psycopg[binary]`, `psycopg-pool` 三个依赖,版本已 pin
- [ ] `pip install -e .` 在 venv 里跑成功无冲突
- [ ] `src/hermes/data/migrations/yoyo.ini` 存在,可被 yoyo 识别
- [ ] `src/hermes/data/migrations/{0001,0002,0003}-*.sql` + `.rollback.sql` 六个文件存在
- [ ] 每个 up SQL 头部带完整 metadata(per migration_tooling.md §5.3)
- [ ] `scripts/migrate.sh apply | rollback | status` 三命令可用
- [ ] `scripts/lint-migrations.sh` 跑通,无报错
- [ ] `hermes-tsdb` 容器内 `\dt` 显示 `klines`, `book_tickers`, `trades` 三张表
- [ ] `SELECT * FROM timescaledb_information.hypertables` 显示三张 hypertable
- [ ] `SELECT * FROM timescaledb_information.jobs` 显示三个 compression jobs
- [ ] book_tickers / trades 有 retention policy,klines 没有
- [ ] Smoke test 通过:三张表分别 INSERT 1 条 + SELECT 1 条 + 数据精度正确
- [ ] 完整 apply → rollback → apply 跑过一遍,幂等性确认
- [ ] 7 个 commit 全部 push 到 `origin/main`
- [ ] `PROGRESS.md` 标记 Phase 3.A.1 complete

---

## 10. 给执行者(下次会话的 AI)的开场指引

如果你是接下来负责 Phase 3.A.1 的 AI,在动手前请:

### 10.1 读完以下文档

按顺序:

1. `CLAUDE.md` —— 协作规约
2. `PHASE_3A1_SCOPE.md` —— 本文(你正在读)
3. `docs/architecture/timescaledb_schema.md` —— SQL 列定义来源
4. `docs/architecture/data_layer.md` —— 上下文(虽然 3.A.1 不写 Python)
5. `docs/architecture/migration_tooling.md` —— SQL 文件模板与命名约定
6. `PHASE_3A_SESSION_NOTES.md` —— 容器搭建的 session 笔记

### 10.2 第一句话对用户说

```
我接手 Phase 3.A.1,目标是把三张 hypertable 真正建到 hermes-tsdb 容器里。
我已读完 PHASE_3A1_SCOPE.md + 三份架构文档。

开干前先跑 §5 Pre-flight checklist。第一步是 Step 0:回查 BookTicker dataclass。
准备好了吗?跑这条命令:

  cat src/hermes/exchanges/binance_contracts.py | grep -A 25 "class BookTicker"

把输出贴回来,我根据结果决定是直接照设计走、还是需要调整 schema。
```

### 10.3 工作纪律

- **绝对不许自驱推进**:每个 commit 用户必须显式 `go`,否则停
- **绝对不写 Python 代码**(除了 `__init__.py` 空文件):Phase 3.C 的事
- **每个 migration 单独 apply 验证后再写下一个**:不批量
- **bash 命令贴在 `(venv) xinyu@trading-tokyo-01:~/hermes_ai$` 那个真终端**,不是 Claude Code 对话框,不是网页对话框
- **大文件创建走 VS Code 编辑器,不走 bash heredoc**(3.A.0 期间踩过坑,反引号被 paste filter 吃)

---

## 11. 未在本 SCOPE 内的待办(Phase 3.A.1 之后)

提醒下次会话之后的 AI,以下事项**不在 3.A.1 范围内**,但已知存在:

- `src/hermes/data/pool.py` 实现 → 3.C
- `src/hermes/data/{models,converters}.py` → 3.C
- `src/hermes/data/writers/*.py` → 3.C
- Async writer 的 batch / flush / 反压 → 3.C
- Integration test 的 transactional fixture → 3.D
- WsClient → dispatcher → writers 端到端 e2e → 3.B + 3.C
- GitHub Actions workflow → 3.C 之后
- `.env` 的 pydantic-settings 加载机制 → 3.C
- Mainnet runbook → Phase 5+

---

**End of document.**