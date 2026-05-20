# Data Layer Module Boundaries — Phase 3.A.0

> **Status**: Design document. No code written yet.
> **Phase**: 3.A.0 (Discovery + Decisions)
> **Scope**: `src/hermes/data/` 模块切分、连接池策略、async writer 模型、与 exchanges 层的对接草图、测试策略。
> **Companions**: `timescaledb_schema.md` (PG 侧 schema),`migration_tooling.md` (DDL 部署)。

---

## 1. 范围与目标

本文档定义 Phase 3 持久化层的 **Python 侧模块边界**:

- `src/hermes/data/` 内部的子模块切分(职责清单)
- 连接池技术选型 + size 决策
- Async writer 的队列/批量/反压模型
- 与 `BinanceWsClient.stream()` 的对接形态(草图,不实现)
- 测试三层结构与隔离策略

**不解决**(留给后续):

- 具体 Python 代码实现 → Phase 3.C
- migration 工具与脚本目录约定 → `migration_tooling.md`
- ingestion 调度与生命周期管理 → Phase 3.B
- orchestrator 模块设计 → Phase 4+
- 查询路径(读取 API)→ Phase 4 回测引擎落地时再定

---

## 2. 模块切分总览

### 2.1 目录树

```
src/hermes/data/
├── __init__.py
├── pool.py                       # AsyncConnectionPool 包装 + 配置加载
├── models.py                     # DB row 形态(TypedDict / dataclass)
├── converters.py                 # binance_contracts.* → models.* 的纯函数
├── writers/
│   ├── __init__.py
│   ├── base.py                   # AbstractWriter:队列 + flush 调度骨架
│   ├── kline_writer.py
│   ├── book_ticker_writer.py
│   └── trade_writer.py
└── migrations/                   # yoyo 脚本目录(见文档 3)
```

### 2.2 文件职责

| 文件 | 职责 | 不做 |
|---|---|---|
| `__init__.py` | 公开 API 导出:`DataPool`, `KlineWriter`, `BookTickerWriter`, `TradeWriter`, models | 业务逻辑 |
| `pool.py` | 创建/持有 `psycopg_pool.AsyncConnectionPool`,从 `~/hermes_ai/infra/.env` 读 DSN | 任何 DDL / DML |
| `models.py` | `KlineRow` / `BookTickerRow` / `TradeRow` —— PG row 的 Python 表示;字段名与表列名严格一致 | 转换逻辑、I/O |
| `converters.py` | `kline_to_row(k: Kline) -> KlineRow` 等纯函数;ms epoch → datetime、列名映射 | 任何状态、I/O |
| `writers/base.py` | `AbstractWriter`:queue、batch、flush 调度的共通骨架;泛型化 row 类型 | 具体 SQL |
| `writers/kline_writer.py` | `KlineWriter(AbstractWriter[KlineRow])`:`ON CONFLICT DO UPDATE` 语义 | 跨表逻辑 |
| `writers/book_ticker_writer.py` | `BookTickerWriter`:`ON CONFLICT DO NOTHING` | 同上 |
| `writers/trade_writer.py` | `TradeWriter`:`ON CONFLICT DO NOTHING` | 同上 |
| `migrations/` | yoyo 脚本目录(空 placeholder,Phase 3.A.1 才填) | — |

### 2.3 为什么 `models.py` 与 `converters.py` 分开

- `models.py` 是**数据形态**(无逻辑),给 type checker / IDE 提示 / row factory 用
- `converters.py` 是**纯函数转换**,可以单独 unit test 而无需起 PG
- 两者揉在一起会让 `models` 难以 import(转换函数可能依赖 datetime/Decimal helpers)

### 2.4 为什么 `writers/` 切 3 个文件而不是单文件

三张表的 `ON CONFLICT` 语义不同:

- klines:`DO UPDATE SET ...`(覆盖未闭合 → 闭合)
- book_tickers / trades:`DO NOTHING`(重复跳过)

写在一个文件里会变成又长又烂的 if/elif 分支;切开后每个 writer 的 SQL 模板自包含,可读性强,以后加新表(funding rate / mark price)只是新增一个文件。

---

## 3. 连接池设计

### 3.1 技术选型

**`psycopg_pool.AsyncConnectionPool`**(psycopg3 官方异步池)。

| 备选 | 否决理由 |
|---|---|
| `asyncpg` | 不在 psycopg 生态;NUMERIC 默认转 `str`,需自写 codec(违反"零适配器"原则);测试夹具生态弱 |
| `aiopg` | 基于 psycopg2,异步性能差,官方已不推荐 |
| SQLAlchemy `AsyncEngine` | 引入 ORM 全家桶,违反 CLAUDE.md 的"只用 raw psycopg3 + TypedDict/dataclass" |

### 3.2 Pool 配置

```python
# src/hermes/data/pool.py (Phase 3.C 实现,这里仅示意)
AsyncConnectionPool(
    conninfo="postgresql://hermes:<pw>@127.0.0.1:5432/hermes",
    min_size=2,
    max_size=5,
    timeout=10.0,        # 获取连接超时(秒)
    max_idle=300.0,      # 空闲连接 5 分钟后回收
    max_lifetime=3600.0, # 连接最长存活 1 小时,防止 PG 端单连接膨胀
    open=False,          # 显式 .open() 避免 import 时副作用
)
```

### 3.3 Size 决策

- **`min_size=2`**:常驻 2 个,启动期 warm
- **`max_size=5`**:Phase 3 写入路径 3 个(klines / book_tickers / trades 各一个 writer task),加 1-2 个余量给临时查询(回测 / 监控 / migration 工具)
- TimescaleDB pg16 默认 `max_connections=100`,5 个用量极小

未来 Phase 4+ 加策略并发查询,再评估扩到 10-20。**不预先优化**。

### 3.4 DSN 来源

从 `~/hermes_ai/infra/.env` 加载:

```bash
TSDB_HOST=127.0.0.1
TSDB_PORT=5432
TSDB_USER=hermes
TSDB_PASSWORD=<28字符强密码>
TSDB_DB=hermes
```

`pool.py` 用 `python-dotenv` 或 `pydantic-settings` 加载(选型留到 3.C 实现时定,**本文档不固化**)。

⚠️ **不允许**:DSN 硬编码进 Python 源码、连接串出现在日志、`.env` 进 git。

---

## 4. Models 与 Converters

### 4.1 Models 命名约定

DB row 类型用 **`<Entity>Row` 后缀**,与 Phase 2 dataclass 区分:

```python
# src/hermes/data/models.py(示意,Phase 3.C 实现)
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

@dataclass(frozen=True, slots=True)
class KlineRow:
    symbol: str
    interval: str
    open_time: datetime
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    quote_volume: Decimal
    trades: int
    taker_buy_base: Decimal
    taker_buy_quote: Decimal
    is_closed: bool

@dataclass(frozen=True, slots=True)
class BookTickerRow:
    symbol: str
    received_at: datetime
    update_id: int
    bid_price: Decimal
    bid_qty: Decimal
    ask_price: Decimal
    ask_qty: Decimal

@dataclass(frozen=True, slots=True)
class TradeRow:
    symbol: str
    trade_id: int
    trade_time: datetime
    price: Decimal
    qty: Decimal
    is_buyer_maker: bool
```

**字段名严格 = `timescaledb_schema.md` 中的列名**(包括缩短的 `taker_buy_base` / `taker_buy_quote`)。

### 4.2 Converters

纯函数,签名固定:

```python
# src/hermes/data/converters.py(示意)
from datetime import datetime, timezone
from hermes.exchanges.binance_contracts import Kline, BookTicker, Trade
from hermes.data.models import KlineRow, BookTickerRow, TradeRow

def _ms_to_dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)

def kline_to_row(k: Kline) -> KlineRow:
    return KlineRow(
        symbol=k.symbol,
        interval=k.interval,
        open_time=_ms_to_dt(k.open_time_ms),
        close_time=_ms_to_dt(k.close_time_ms),
        open=k.open,
        ...
    )
# 类似 book_ticker_to_row, trade_to_row
```

**约束**:

- 纯函数(无 I/O、无副作用)
- 输入 dataclass frozen,输出 dataclass frozen
- 转换错误抛 `ValueError`,**不静默**

### 4.3 BookTicker 的 update_id 问题

参考 `timescaledb_schema.md` §12.1 未决问题。

如果 `BookTicker` dataclass 不含 `update_id`,**converters 不接 `BookTicker`,接原始 WS payload dict**:

```python
# 备选 A:converter 接 dict
def book_ticker_dict_to_row(raw: dict) -> BookTickerRow: ...
```

或:

```python
# 备选 B:converter 接 (BookTicker, update_id) 二元组
def book_ticker_to_row(bt: BookTicker, update_id: int) -> BookTickerRow: ...
```

**倾向 B**(类型更明确,避免 dict 流穿层)。具体 Phase 3.A.1 写代码前先回查 `binance_contracts.py`,如果 dataclass 本身已含 `update_id`,直接用 A 一样的形态(等价于 `BookTicker` → `BookTickerRow`)。

---

## 5. Writer 设计

### 5.1 AbstractWriter 骨架

```python
# src/hermes/data/writers/base.py(示意)
from abc import ABC, abstractmethod
from typing import Generic, TypeVar
import asyncio

RowT = TypeVar("RowT")

class AbstractWriter(ABC, Generic[RowT]):
    def __init__(
        self,
        pool: AsyncConnectionPool,
        queue_maxsize: int = 10_000,
        batch_size: int = 100,
        flush_interval_s: float = 0.5,
    ) -> None:
        self._pool = pool
        self._queue: asyncio.Queue[RowT] = asyncio.Queue(maxsize=queue_maxsize)
        self._batch_size = batch_size
        self._flush_interval = flush_interval_s
        self._task: asyncio.Task | None = None
        self._stopped = asyncio.Event()

    async def put(self, row: RowT) -> None:
        """Producer side. 队满时阻塞(反压)."""
        await self._queue.put(row)

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stopped.set()
        if self._task:
            await self._task

    async def _run(self) -> None:
        """flush loop: 满 batch_size 或超 flush_interval 触发 flush."""
        ...

    @abstractmethod
    def _build_insert_sql(self) -> str:
        """子类提供 INSERT ... ON CONFLICT ... 模板."""

    @abstractmethod
    def _row_to_params(self, row: RowT) -> tuple:
        """子类提供 row → executemany 参数元组."""
```

### 5.2 Concrete Writers 的差异点

| Writer | SQL ON CONFLICT 子句 | 触发情景 |
|---|---|---|
| `KlineWriter` | `ON CONFLICT (symbol, interval, open_time) DO UPDATE SET close = EXCLUDED.close, high = ..., ..., is_closed = EXCLUDED.is_closed` | 未闭合 K 线后续被闭合版本覆盖 |
| `BookTickerWriter` | `ON CONFLICT (symbol, received_at, update_id) DO NOTHING` | WS 重连重发同 update_id |
| `TradeWriter` | `ON CONFLICT (symbol, trade_id, trade_time) DO NOTHING` | 重连重发同 trade_id |

**注意 klines 的 DO UPDATE**:只更新业务字段(OHLC / volume / trades / is_closed),不动主键列。SQL 模板里要列全 UPDATE 字段,**禁止 `EXCLUDED.*` 偷懒**(会更新主键列,违反 PG 约束)。

### 5.3 Writer 不持有 schema 知识

Writers 只知道自己负责的表 + SQL 模板 + row 类型。**表结构变更** → 改 migration(yoyo)+ 改 `models.py` + 改 writer 的 SQL 字符串。三者必须同步,**未来用 codegen 自动同步**(Phase 7+,不在当前范围)。

---

## 6. Async 写入流水线

### 6.1 全景图

```
┌─────────────────┐
│ BinanceWsClient │  (Phase 2 已完成,FROZEN)
│   .stream()     │
└────────┬────────┘
         │ AsyncIterator[Kline | BookTicker | Trade]
         ▼
┌─────────────────────────┐
│ dispatcher task         │  (归属 orchestrator,Phase 4+,本文档只画草图)
│  按 type 路由到不同 queue │
└─┬──────────┬──────────┬─┘
  │          │          │
  ▼          ▼          ▼
queue_k   queue_bt   queue_t        (asyncio.Queue, maxsize=10_000)
  │          │          │
  ▼          ▼          ▼
KlineW    BookTkW    TradeW         (AbstractWriter._run loop)
  │          │          │
  └──────────┴──────────┘
             │
             ▼
     ┌───────────────┐
     │ AsyncConn     │  size=2..5
     │ Pool          │
     └───────┬───────┘
             │
             ▼
       ┌──────────┐
       │ TimescaleDB │  hermes-tsdb (Docker)
       └──────────┘
```

### 6.2 反压(backpressure)

- queue `maxsize=10_000`:满了 `put()` 阻塞,producer(dispatcher)被卡,WsClient 自然减速
- 这是 SOL 量化系统可以接受的行为:**宁愿数据滞后几百 ms,不愿 OOM**
- monitoring(Phase 5+)需要观察 queue depth,超阈值告警

### 6.3 Batch flush 触发条件

**取较早者触发**:

- 队列累计 `batch_size = 100` 条
- 距上次 flush 超过 `flush_interval_s = 500ms`

**初值依据**(可调):

- 100 条 batch:`executemany` 在 100 条规模下效率/延迟平衡点
- 500ms 间隔:实时性需求(book_ticker)与吞吐量的折中

Phase 3.C 上线后跑数据:看 `pg_stat_statements` 的 `mean_exec_time` 和 queue depth p99,再调。

### 6.4 单次 flush 的事务边界

每个 writer 自己一个连接 + 一个事务:

```python
async with self._pool.connection() as conn:
    async with conn.cursor() as cur:
        await cur.executemany(sql, [self._row_to_params(r) for r in batch])
    # async with conn 退出时自动 commit(psycopg3 默认)
```

**不要跨 writer 共享事务** —— 三张表互相独立,出错时局部回滚不影响其他 writer。

### 6.5 失败处理

| 错误类 | 行为 |
|---|---|
| `psycopg.OperationalError`(网络断、PG 重启) | log + 重试 3 次(指数退避 1s/2s/4s);再失败把 batch 暂存 in-memory `_dead_letter` list,后续 flush 时优先重投 |
| `psycopg.IntegrityError`(数据违反约束,理论上不该发生) | log ERROR,丢弃该 batch,不阻塞后续 |
| `psycopg.DataError`(类型不匹配,bug) | log CRITICAL,丢弃 batch,告警 |
| 其他未知 | log CRITICAL,丢弃 batch |

`_dead_letter` list 设上限(如 10k 行),超过后丢最老的;监控暴露这个指标。

详细的 retry 策略 Phase 3.C 实现时再固化,**本文档只声明语义**。

---

## 7. 与 exchanges 层的对接

### 7.1 关键边界:`data/` 不直接依赖 `exchanges/`

`writers/*` 接收 `models.*Row` 类型,**不**接 `binance_contracts.*` 类型。这样的好处:

- 未来加 OKX / Bybit,只需扩 `converters/` 模块,writers 不动
- 数据层可独立测试,不用 mock exchanges 整套

依赖方向:

```
exchanges/binance_contracts.py     (Phase 2, FROZEN)
        │
        ▼ import
hermes/data/converters.py          (新)
        │
        ▼ produces
hermes/data/models.py              (新)
        │
        ▼ consumed by
hermes/data/writers/*              (新)
```

`exchanges/` 完全不知道 `data/` 存在(单向)。

### 7.2 Dispatcher 草图(归属 orchestrator,不在 data/)

```python
# 示意 — 实际归属待 Phase 4+ orchestrator 模块设计
async def dispatch(
    ws_client: BinanceWsClient,
    kline_writer: KlineWriter,
    bt_writer: BookTickerWriter,
    trade_writer: TradeWriter,
) -> None:
    from hermes.data.converters import kline_to_row, book_ticker_to_row, trade_to_row

    async for msg in ws_client.stream():
        match msg:
            case Kline() if msg.is_closed:
                await kline_writer.put(kline_to_row(msg))
            case BookTicker():
                # update_id 提取问题见 §4.3
                await bt_writer.put(book_ticker_to_row(msg, update_id=...))
            case Trade():
                await trade_writer.put(trade_to_row(msg))
            case _:
                pass  # 其他类型(未来扩展)
```

**Phase 3.A.0 不固化 dispatcher 位置**,只承诺:

- dispatcher 不在 `src/hermes/data/`
- dispatcher 不在 `src/hermes/exchanges/`(FROZEN)
- 候选位置 `src/hermes/orchestrator/`(目前 stub)

### 7.3 未闭合 K 线的过滤

参考 `timescaledb_schema.md` §12.2:**Phase 3.A.0 默认只写 `is_closed = TRUE`**。dispatcher 里 `case Kline() if msg.is_closed` 守卫表达这一点。

未来若策略需要未闭合 K 线落库做实时特征,改 dispatcher,**不改 schema、不改 writer**。

---

## 8. 测试策略

### 8.1 三层结构

| 层 | 位置 | 跑什么 | 跑的速度 | 依赖 |
|---|---|---|---|---|
| Unit | `tests/unit/data/` | converters / models 形态 / writer batch 调度逻辑(mock pool) | 毫秒级 | 无 |
| Integration | `tests/integration/data/` | 真 PG 容器:`pool.py` / writer 端到端 INSERT / migration apply | 秒级 | `hermes-tsdb` 跑着 |
| E2E | `tests/e2e/data/` | testnet WsClient → dispatcher → writers → 查询验证 | 分钟级 | 网络 + PG |

### 8.2 Unit 测试约定

- 完全无 I/O(mock `AsyncConnectionPool`、mock `executemany`)
- 覆盖:converter 每个字段的转换正确性、AbstractWriter 的 batch 触发时机、错误分支
- 不允许 import `psycopg`(只 mock 它)

### 8.3 Integration 测试约定:Transactional Fixture

每个 test 在独立事务里跑,结束**回滚**(不污染数据库):

```python
# 示意 — tests/integration/data/conftest.py
@pytest_asyncio.fixture
async def transactional_conn(pool):
    async with pool.connection() as conn:
        await conn.set_autocommit(False)
        async with conn.transaction():  # SAVEPOINT
            yield conn
            # 退出 transaction context 时自动 ROLLBACK SAVEPOINT
        await conn.rollback()  # 兜底
```

**关键约束**:

- 每个 test 独立连接、独立事务
- 不能 `commit()` —— 数据只在事务可见,test 结束消失
- 测试 fixture 用 dedicated test db(`hermes_test`)还是直接 `hermes` db 走 ROLLBACK?**倾向后者**(简单),前者备选(更安全)

⚠️ **Phase 3.A.0 不固化 test db 命名**,留到 3.A.1 或 3.C 实现时定。

### 8.4 E2E 测试约定

- 只跑在 CI / 本地手动触发,不进默认 `pytest` 流水线(`pytest -m e2e`)
- 真连 testnet WS,跑 30-60s,验证至少有 K 线/book_ticker/trade 各 N 条入库
- 测试结束 **drop test 数据**(根据写入时间戳过滤)

### 8.5 Lint / Type 覆盖

- ruff 规则集照 CLAUDE.md(`E, F, I, N, W, UP, B, SIM, RUF`,行长 100)
- mypy strict mode 覆盖 `src/hermes/data/`
- `from hermes.data.xxx import ...` 导入(`pythonpath=src`)

---

## 9. 错误处理与重连

### 9.1 PG 连接断开

`psycopg_pool` 内置健康检查,坏连接自动剔除。writer 收到 `OperationalError` 触发 §6.5 的重试逻辑。

### 9.2 容器重启

`hermes-tsdb` 重启场景(运维手动 / OOM kill):

- writer 的 retry 期间数据暂存 in-memory queue + `_dead_letter` list
- 容器恢复后自动重连,flush 队列
- 期间 WS 持续灌数据,**queue 满了开始反压**(预期行为)

### 9.3 Writer task 异常崩溃

`asyncio.create_task` 包装,task 内部全局 try/except 兜底:

- 不可恢复异常 → log CRITICAL + 触发 graceful shutdown(其他 writer 也停)
- 可恢复异常 → log ERROR + 继续

具体策略 Phase 3.C 实现,**本文档不固化**。

### 9.4 Migration 期间的写入

参考 `migration_tooling.md`:migration 应用期间禁止写入(运维流程 = 停 writer → apply migration → 起 writer)。**不支持热 migration**,因为 schema 变更涉及锁。

---

## 10. 不在本文档范围内

明确**不**在本文档解决:

- 具体 Python 实现 → Phase 3.C
- migration 工具与目录约定 → `migration_tooling.md`
- ingestion 调度(WsClient 启动 / 优雅停机)→ Phase 3.B
- orchestrator 模块边界 → Phase 4+
- 查询路径(读取 API、缓存策略)→ Phase 4 回测引擎落地
- 监控指标(queue depth / flush latency)→ Phase 5
- mainnet 切换前的运维 runbook → `docs/operations/`(独立文档)

---

## 11. 未决问题清单

落地前(Phase 3.C 写代码时)必须解决:

1. **`BookTicker.update_id` 来源**:见 §4.3 + `timescaledb_schema.md` §12.1。先回查 `binance_contracts.py`。
2. **DSN 加载机制**:`python-dotenv` vs `pydantic-settings` vs 自写 `os.environ` 读取。倾向 `pydantic-settings`(已是事实标准 + type-safe),但若引入 pydantic v2 与其他依赖冲突,降级 `python-dotenv`。3.C 实战前定。
3. **Test db 命名**:`hermes_test` dedicated 还是直接 `hermes` + ROLLBACK?见 §8.3。
4. **Dispatcher 归属**:候选 `src/hermes/orchestrator/`,但 orchestrator 模块本身 Phase 4+ 才设计。Phase 3.B/C 之间临时位置可放 `src/hermes/data/_dispatcher_tmp.py` 加 TODO 注释。Phase 3.A.0 不强制定。
5. **batch_size / flush_interval 调参**:100 / 500ms 是初值,Phase 3.C 实战后 profile 调整。
6. **`_dead_letter` 上限策略**:10k 行是初值;超限时 FIFO 丢最老,还是直接告警停 writer?Phase 3.C 定。
7. **graceful shutdown 协议**:writer.stop() 应等 queue 排空再停,还是设 timeout 后强停?Phase 3.B/C 定。

---

**End of document.**