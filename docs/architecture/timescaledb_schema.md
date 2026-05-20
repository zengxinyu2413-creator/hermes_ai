# TimescaleDB Schema Design — Phase 3.A.0

> **Status**: Design document. No tables created yet.
> **Phase**: 3.A.0 (Discovery + Decisions)
> **Scope**: Schema-level decisions for three hypertables backing Phase 3 data persistence.
> **Companions**: `data_layer.md` (Python-side boundaries), `migration_tooling.md` (DDL deployment).

---

## 1. 概述与目标

Phase 3 引入持久化数据层,把 Phase 2 已经能从 Binance WebSocket 拿到的实时数据沉淀到 TimescaleDB,供:

- **回测引擎** 读历史 K 线
- **策略层** 跑特征工程时读历史 book ticker / trades
- **监控** 做数据完整性检查(gap detection)

本文档只定义 schema —— 表结构、索引、hypertable 策略、压缩、retention。**不涉及**:

- 写入路径(`src/hermes/data/writers/`,见 `data_layer.md`)
- DDL 部署方式(`docs/architecture/migration_tooling.md`)
- Ingestion 调度(Phase 3.B)
- Async writer 实现(Phase 3.C)

---

## 2. 三张表的角色定位

| 表 | 数据源 | 更新频率 | 用途 | Retention |
|---|---|---|---|---|
| `klines` | Binance kline stream (`<symbol>@kline_<interval>`) | 1m / 5m / 15m / 1h / 4h / 1d | 回测、特征工程、HMM regime 输入 | **永久** |
| `book_tickers` | Binance bookTicker stream (`<symbol>@bookTicker`) | ~10/s per symbol | 微结构特征、slippage 估计、订单簿状态快照 | **30 天** |
| `trades` | Binance trade stream (`<symbol>@trade`) | 每笔成交 | tape reading、买卖压力特征、VWAP 计算 | **30 天** |

**为什么 klines 永久、其他两张 30 天**:K 线是聚合后的低频数据,长期保留代价低且对策略回测必需。book_ticker 和 trades 是高频原始数据,30 天足够做近端特征工程,更长的历史在策略上边际收益低、存储成本高(单 symbol 每天 ~百万行)。

---

## 3. 类型映射:Python `Decimal` ↔ PostgreSQL `NUMERIC(18,8)`

**强制约定**(从 CLAUDE.md):所有价格/数量字段在 Python 侧用 `Decimal`,在 PG 侧用 `NUMERIC(18,8)`。**禁止 `float` / `DOUBLE PRECISION`**。

| 维度 | 选择 | 理由 |
|---|---|---|
| 精度 | `18` 位有效数字 | SOL 价格 ~$200,精度需求到 8 位小数;加上整数部分 10 位,18 足够,留余量 |
| 标度 | `8` 位小数 | Binance API 大多数 symbol 的 `pricePrecision` / `quantityPrecision` 上限就是 8 |
| Python ↔ PG 驱动 | `psycopg3` 默认 | `psycopg3` 自动把 PG `NUMERIC` 转成 Python `Decimal`,无需 adapter |
| 字面量构造 | `Decimal("123.45678901")` | **永远从字符串构造**,禁止 `Decimal(123.45)`(浮点污染) |

**禁止字段类型清单**:

- ❌ `REAL` / `DOUBLE PRECISION` —— 任何价格量字段一律不允许
- ❌ `FLOAT` / `FLOAT8` —— 同上
- ✅ `BIGINT` —— 仅用于 trade_id / update_id 等纯整数 ID
- ✅ `INTEGER` —— 用于 trade count 等小整数
- ✅ `BOOLEAN` —— 用于 `is_buyer_maker` / `is_closed` 等
- ✅ `TEXT` —— 用于 symbol / interval(短字符串,无需 VARCHAR(n))
- ✅ `TIMESTAMPTZ` —— 所有时间列

---

## 4. 时间列约定:ms epoch ↔ TIMESTAMPTZ

### 4.1 决策

**所有 hypertable 的时间列用 `TIMESTAMPTZ`,不用 `BIGINT` 毫秒戳。**

### 4.2 理由

- TimescaleDB 的所有时间维护函数(`time_bucket`、`add_retention_policy`、`add_compression_policy`、`drop_chunks`)都以 `INTERVAL` 操作,`TIMESTAMPTZ` 是最舒服的输入
- 查询可读性:`WHERE open_time > NOW() - INTERVAL '7 days'` vs `WHERE open_time_ms > (extract(epoch from now()) * 1000 - 7*86400*1000)::bigint`
- BI 工具(Grafana、DBeaver、Metabase)自动识别为时间轴
- TimescaleDB 也支持 `BIGINT` 模式,但生态远不如 `TIMESTAMPTZ` 成熟

### 4.3 Phase 2 contract 不变

`src/hermes/exchanges/binance_contracts.py` 里的 `Kline.open_time_ms` / `Kline.close_time_ms` / `BookTicker.received_at_ms` / `Trade.time_ms` **保持 `int` 类型不动**(那是 frozen contract)。

转换发生在写入层(`src/hermes/data/writers/`,Phase 3.C):

```python
# Python 侧
open_time_dt = datetime.fromtimestamp(kline.open_time_ms / 1000, tz=timezone.utc)
```

写入时由 `psycopg3` 自动绑定为 `TIMESTAMPTZ`,无需手动 cast。

### 4.4 时区

**所有 TIMESTAMPTZ 列存 UTC**。PG 内部存储就是 UTC,显示时按 session timezone。后续 Grafana / 报表展示按需 `AT TIME ZONE 'Asia/Tokyo'` 转换。

---

## 5. `klines` 表设计

### 5.1 DDL(草案,不执行)

```sql
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

SELECT create_hypertable('klines', 'open_time', chunk_time_interval => INTERVAL '7 days');
```

### 5.2 字段说明

| 列 | 类型 | 来源(Kline dataclass) | 备注 |
|---|---|---|---|
| `symbol` | TEXT | `Kline.symbol` | 大写,如 `"SOLUSDT"` |
| `interval` | TEXT | `Kline.interval` | 如 `"1m"` / `"1h"` |
| `open_time` | TIMESTAMPTZ | `Kline.open_time_ms` (转换) | Hypertable 时间列 |
| `close_time` | TIMESTAMPTZ | `Kline.close_time_ms` (转换) | 索引参考 |
| `open/high/low/close` | NUMERIC(18,8) | 同名 | |
| `volume` | NUMERIC(18,8) | `Kline.volume` | base asset 数量 |
| `quote_volume` | NUMERIC(18,8) | `Kline.quote_volume` | quote asset(USDT)数量 |
| `trades` | INTEGER | `Kline.trades` | 该 K 线内成交笔数 |
| `taker_buy_base` | NUMERIC(18,8) | `Kline.taker_buy_base_volume` | |
| `taker_buy_quote` | NUMERIC(18,8) | `Kline.taker_buy_quote_volume` | |
| `is_closed` | BOOLEAN | `Kline.is_closed` | 仅 `TRUE` 的 K 线允许进入主表(未闭合的不写) |

### 5.3 主键

`(symbol, interval, open_time)` —— 业务唯一性:同 symbol + 同 interval + 同开盘时刻只可能有一根 K 线。

主键自带 BTree 索引,覆盖最常见的查询模式:

```sql
SELECT * FROM klines
WHERE symbol = 'SOLUSDT' AND interval = '1m'
  AND open_time BETWEEN $1 AND $2
ORDER BY open_time;
```

### 5.4 chunk_time_interval

**7 天**。

理由:1m K 线 1 个 symbol 1 天 = 1440 行,7 天 = ~10k 行。一个 chunk 一万行级别是 TimescaleDB 推荐的舒适区(官方建议每 chunk 25M ~ 10B 行之间,但小数据集偏小没问题;过碎反而拖累 planner)。

未来如果 symbol 数量爆增(>50)或加入 tick 级 K 线,可重新评估。

### 5.5 Compression Policy

```sql
ALTER TABLE klines SET (
    timescaledb.compress,
    timescaledb.compress_orderby = 'open_time DESC',
    timescaledb.compress_segmentby = 'symbol, interval'
);
SELECT add_compression_policy('klines', INTERVAL '30 days');
```

- **超过 30 天的 chunk 自动压缩**
- `segmentby (symbol, interval)`:压缩组内按 symbol+interval 聚类,提升按 symbol 过滤的解压效率
- `orderby (open_time DESC)`:时间倒序排列,贴合回测倒序扫描

### 5.6 Retention Policy

**不设置 `add_retention_policy`**。klines 永久保留。

---

## 6. `book_tickers` 表设计

### 6.1 DDL(草案)

```sql
CREATE TABLE book_tickers (
    symbol       TEXT          NOT NULL,
    received_at  TIMESTAMPTZ   NOT NULL,
    bid_price    NUMERIC(18,8) NOT NULL,
    bid_qty      NUMERIC(18,8) NOT NULL,
    ask_price    NUMERIC(18,8) NOT NULL,
    ask_qty      NUMERIC(18,8) NOT NULL,
    PRIMARY KEY (symbol, received_at)
);

SELECT create_hypertable('book_tickers', 'received_at', chunk_time_interval => INTERVAL '1 day');
```

### 6.2 字段说明

| 列 | 类型 | 来源(BookTicker dataclass) | 备注 |
|---|---|---|---|
| `symbol` | TEXT | `BookTicker.symbol` | |
| `received_at` | TIMESTAMPTZ | `BookTicker.received_at_ms` (转换) | Hypertable 时间列;客户端接收时刻 |
| `bid_price` | NUMERIC(18,8) | `BookTicker.bid_price` | |
| `bid_qty` | NUMERIC(18,8) | `BookTicker.bid_qty` | |
| `ask_price` | NUMERIC(18,8) | `BookTicker.ask_price` | |
| `ask_qty` | NUMERIC(18,8) | `BookTicker.ask_qty` | |

### 6.3 主键

`(symbol, received_at)` —— 二元主键。

**决策记录(Phase 3.A.0 close-out,2026-05-20)**:Phase 2 的 `BookTicker` dataclass 不含 `update_id`(已回查 `src/hermes/exchanges/binance_contracts.py`),且原始 WS payload 的 `u` 字段在 Phase 2 WsClient parse 时已被丢弃。由于 `src/hermes/exchanges/` 是 FROZEN,Phase 3 不能改 dataclass / parser,因此采用**主键退化方案**:

- 二元主键 `(symbol, received_at)`,允许 ms 撞戳时 `ON CONFLICT DO NOTHING` 丢弃后到事件
- 写入语义见 §10:`INSERT ... ON CONFLICT (symbol, received_at) DO NOTHING`

**风险评估**:

- `received_at_ms` 是**本地接收时刻**(非 Binance 撮合时刻),本地接收抖动通常 ≥100µs,真正撞 ms 概率低
- 即使偶发丢失 1-2 条 bookTicker,对采样型微结构特征影响微小(book ticker 本身就是状态快照)
- 若 Phase 4+ 实测撞戳率不可接受,届时考虑解冻 `exchanges/` 加 `update_id`,或在 dispatcher 端加 sequence counter

### 6.4 chunk_time_interval

**1 天**。

理由:1 个 symbol 1 天约 ~864k 行(假设 10/s),5 个 symbol 就是 ~4.3M 行/天。1 天 1 chunk 是 retention(30 天)的天然切片单位,`drop_chunks` 可以整 chunk 删除,极快。

### 6.5 Compression Policy

```sql
ALTER TABLE book_tickers SET (
    timescaledb.compress,
    timescaledb.compress_orderby = 'received_at DESC',
    timescaledb.compress_segmentby = 'symbol'
);
SELECT add_compression_policy('book_tickers', INTERVAL '7 days');
```

- **超过 7 天的 chunk 压缩**(retention 30 天,中间 7-30 天压缩省空间)
- `segmentby symbol`:按 symbol 聚簇,大多数查询按单 symbol 过滤

### 6.6 Retention Policy

```sql
SELECT add_retention_policy('book_tickers', INTERVAL '30 days');
```

**超过 30 天的 chunk 自动 drop**。

---

## 7. `trades` 表设计

### 7.1 DDL(草案)

```sql
CREATE TABLE trades (
    symbol          TEXT          NOT NULL,
    trade_id        BIGINT        NOT NULL,
    trade_time      TIMESTAMPTZ   NOT NULL,
    price           NUMERIC(18,8) NOT NULL,
    qty             NUMERIC(18,8) NOT NULL,
    is_buyer_maker  BOOLEAN       NOT NULL,
    PRIMARY KEY (symbol, trade_id, trade_time)
);

SELECT create_hypertable('trades', 'trade_time', chunk_time_interval => INTERVAL '1 day');
```

### 7.2 字段说明

| 列 | 类型 | 来源(Trade dataclass) | 备注 |
|---|---|---|---|
| `symbol` | TEXT | `Trade.symbol` | |
| `trade_id` | BIGINT | `Trade.trade_id` | Binance 每 symbol 全局递增 |
| `trade_time` | TIMESTAMPTZ | `Trade.time_ms` (转换) | Hypertable 时间列;**交易所撮合时刻**(非客户端接收) |
| `price` | NUMERIC(18,8) | `Trade.price` | |
| `qty` | NUMERIC(18,8) | `Trade.qty` | |
| `is_buyer_maker` | BOOLEAN | `Trade.is_buyer_maker` | TRUE = 卖方主动(taker sell);买卖压力指标 |

### 7.3 主键

`(symbol, trade_id, trade_time)` —— 三元主键。

**为什么含 `trade_time`**:TimescaleDB hypertable 的 PRIMARY KEY 必须包含时间分区列。`trade_id` 在 Binance 侧每 symbol 全局唯一递增,逻辑上 `(symbol, trade_id)` 已足够,但 hypertable 约束强制加入 `trade_time`。语义上仍是"该 trade_id 唯一标识一笔成交",`trade_time` 只是分区辅助。

### 7.4 chunk_time_interval

**1 天**(同 book_tickers,理由相同)。

### 7.5 Compression Policy

```sql
ALTER TABLE trades SET (
    timescaledb.compress,
    timescaledb.compress_orderby = 'trade_time DESC, trade_id DESC',
    timescaledb.compress_segmentby = 'symbol'
);
SELECT add_compression_policy('trades', INTERVAL '7 days');
```

### 7.6 Retention Policy

```sql
SELECT add_retention_policy('trades', INTERVAL '30 days');
```

---

## 8. Hypertable 策略汇总

| 表 | 时间列 | chunk_time_interval | 主键 | 压缩 | Retention |
|---|---|---|---|---|---|
| `klines` | `open_time` | 7 天 | `(symbol, interval, open_time)` | 30d 后压缩 | 永久 |
| `book_tickers` | `received_at` | 1 天 | `(symbol, received_at)` | 7d 后压缩 | 30 天 |
| `trades` | `trade_time` | 1 天 | `(symbol, trade_id, trade_time)` | 7d 后压缩 | 30 天 |

---

## 9. 与 `binance_contracts.py` 的字段对应总表

### 9.1 Kline → klines

| Python(`Kline` dataclass) | 类型 | PG(`klines`) | 类型 | 转换 |
|---|---|---|---|---|
| `symbol` | `str` | `symbol` | TEXT | 直接 |
| `interval` | `str` | `interval` | TEXT | 直接 |
| `open_time_ms` | `int` | `open_time` | TIMESTAMPTZ | `fromtimestamp(ms/1000, UTC)` |
| `close_time_ms` | `int` | `close_time` | TIMESTAMPTZ | 同上 |
| `open` | `Decimal` | `open` | NUMERIC(18,8) | 直接 |
| `high` | `Decimal` | `high` | NUMERIC(18,8) | 直接 |
| `low` | `Decimal` | `low` | NUMERIC(18,8) | 直接 |
| `close` | `Decimal` | `close` | NUMERIC(18,8) | 直接 |
| `volume` | `Decimal` | `volume` | NUMERIC(18,8) | 直接 |
| `quote_volume` | `Decimal` | `quote_volume` | NUMERIC(18,8) | 直接 |
| `trades` | `int` | `trades` | INTEGER | 直接 |
| `taker_buy_base_volume` | `Decimal` | `taker_buy_base` | NUMERIC(18,8) | 列名缩短 |
| `taker_buy_quote_volume` | `Decimal` | `taker_buy_quote` | NUMERIC(18,8) | 列名缩短 |
| `is_closed` | `bool` | `is_closed` | BOOLEAN | 直接 |

### 9.2 BookTicker → book_tickers

| Python(`BookTicker` dataclass) | 类型 | PG(`book_tickers`) | 类型 | 转换 |
|---|---|---|---|---|
| `symbol` | `str` | `symbol` | TEXT | 直接 |
| `received_at_ms` | `int` | `received_at` | TIMESTAMPTZ | `fromtimestamp(ms/1000, UTC)` |
| `bid_price` | `Decimal` | `bid_price` | NUMERIC(18,8) | 直接 |
| `bid_qty` | `Decimal` | `bid_qty` | NUMERIC(18,8) | 直接 |
| `ask_price` | `Decimal` | `ask_price` | NUMERIC(18,8) | 直接 |
| `ask_qty` | `Decimal` | `ask_qty` | NUMERIC(18,8) | 直接 |

### 9.3 Trade → trades

| Python(`Trade` dataclass) | 类型 | PG(`trades`) | 类型 | 转换 |
|---|---|---|---|---|
| `symbol` | `str` | `symbol` | TEXT | 直接 |
| `trade_id` | `int` | `trade_id` | BIGINT | 直接 |
| `time_ms` | `int` | `trade_time` | TIMESTAMPTZ | `fromtimestamp(ms/1000, UTC)` |
| `price` | `Decimal` | `price` | NUMERIC(18,8) | 直接 |
| `qty` | `Decimal` | `qty` | NUMERIC(18,8) | 直接 |
| `is_buyer_maker` | `bool` | `is_buyer_maker` | BOOLEAN | 直接 |

---

## 10. 写入语义(预告,详见 `data_layer.md`)

本节只声明语义,**不实现**:

- **klines**:`INSERT ... ON CONFLICT (symbol, interval, open_time) DO UPDATE` —— 未闭合 K 线可能被后续闭合版本覆盖
- **book_tickers**:`INSERT ... ON CONFLICT (symbol, received_at) DO NOTHING` —— 同 (symbol, received_at) 撞戳时跳过(WS 重连重发,或 ms 级别真实撞戳)
- **trades**:`INSERT ... ON CONFLICT DO NOTHING` —— trade_id 全局唯一,重复跳过

---

## 11. 不在本文档范围内的内容

明确**不**在本文档解决,留给后续阶段:

- 写入层连接池配置 → `data_layer.md`
- batch flush 策略 → `data_layer.md` + Phase 3.C
- migration 工具与目录约定 → `migration_tooling.md`
- continuous aggregate(物化 K 线聚合视图)→ Phase 3.D 或更晚
- multi-node / replica → 不在 v6 计划内
- 备份策略 → `docs/operations/`(后续单独文档)

---

## 12. 未决问题清单

落地前(Phase 3.A.1 准备写 migration 时)必须解决:

1. ~~**`BookTicker` dataclass 是否含 `update_id`**~~ — **已决(Phase 3.A.0 close-out,2026-05-20)**:dataclass 不含 `update_id`,原始 WS payload 的 `u` 在 Phase 2 parse 时已被丢弃。`exchanges/` FROZEN,采用主键退化方案 `(symbol, received_at)` + `DO NOTHING`,详见 §6.3。
2. **`klines` 是否要把未闭合 K 线落库**:倾向"只写 `is_closed = TRUE` 的"。但 Phase 3.B ingestion 设计可能需要落未闭合行以支持实时策略,届时表里要不要存 `is_closed = FALSE` 的中间状态?当前文档默认"只写闭合",该字段保留是为了 schema 兼容未来变更。
3. **额外二级索引**:Phase 3.A.0 不预先优化,仅依赖主键。3.C 写入实战后跑慢查询分析,再补 `CREATE INDEX`。
4. **压缩 segmentby 的基数权衡**:`compress_segmentby = 'symbol'` 假设我们交易的 symbol 数量在 5~20 区间。若未来扩到 100+,segmentby 基数过高会影响压缩率,需重评估。
5. **trades 主键的 hypertable 约束验证**:Phase 3.A.1 写完 migration、实际 `CREATE TABLE` 时,若 PG 报错 "primary key must include time partitioning column",当前 §7.3 的设计已满足;若 TimescaleDB 2.27 允许不含时间列的 PK(罕见),可降级为 `(symbol, trade_id)`。先按当前 DDL 走。

---

**End of document.**