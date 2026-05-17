# Phase 2.D.6 — 已完成

## 三个子项全部交付

| 子项 | commit | 内容 |
|------|--------|------|
| 2.D.6-i  | `4f18693` | WS keepalive 常量 + ping_interval/timeout 传参 + structlog 安全网（83 → 91 个测试）|
| 2.D.6-ii | `094bb24` | WsMetrics frozen dataclass + BinanceWsClient 四项计数器 |
| 2.D.6-iii| `c8e93f7` | TestWsMetrics 6 个测试（91 → 97 个测试，全绿）|

无 2.D.6-iv。Phase 2.D.6 到此完整关闭。

## BinanceWsClient 功能层现状（全部完成）

- [x] 流解析（kline / book_ticker / trade / UNKNOWN）
- [x] 读循环 + 有界队列 + 背压
- [x] 指数退避重连（含 jitter、60s 上限、干净关闭重置计数）
- [x] WebSocket keepalive（ping_interval=20, ping_timeout=10）
- [x] 结构化日志（structlog：connected / reconnect_scheduled / run_cancelled）
- [x] WsMetrics 快照（messages_received_total, messages_by_kind, reconnect_count, current_attempt）

---

## 下一步：Phase 2.E — 向上一层（待讨论后确定）

`binance_ws.py` 和 `binance_rest.py` 已完整。所有上层模块目前是空 stub：

```
src/hermes/regime/        __init__.py 只
src/hermes/monitoring/    __init__.py 只
src/hermes/strategies/    __init__.py 只
src/hermes/risk/          __init__.py 只
src/hermes/execution/     __init__.py 只
src/hermes/orchestrator/  __init__.py 只
src/hermes/backtest/      __init__.py 只
```

### 候选方向（开始前先和用户确认选哪个）

- **2.E.1 monitoring** — 把 WsMetrics 接入 Prometheus / StatsD，或实现一个轻量 in-process 指标汇总器
- **2.E.2 regime** — 市场状态检测（趋势 / 震荡 / 高波动），消费 `StreamMessage` kline 流
- **2.E.3 orchestrator** — 把 WsClient + RestClient 组装成一个可启动的进程入口，管理生命周期
- **2.E.4 integration tests** — 补充 `tests/integration/`，对真实 testnet 跑冒烟测试

**建议**：下个 session 开始时先讨论选哪个方向，再拆子项。
