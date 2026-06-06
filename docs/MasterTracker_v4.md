# HermesAI 项目节点控制主表 v4（对齐仓库现实，2026-06-06）

## §0 编号体系与口径

- v4 取代 v3。v3 称「M3 全未开始、grep 未发现实现」已被仓库证伪（PREC/RISK/EXEC 三模块 + testnet 三相真单 + b3b-live 首单全闭环），作废。
- 进度以仓库 git log 为最终准，文档次之（承 22/23.md 铁律）。
- 当前锚：HEAD（44.md 落档 commit 后由 Iris 填）/ baseline 738 passed / ce9 五基线见 §6.6。
- 编号沿用：LC-* 生命周期 / PREC-* 精度 / RISK-* 风控 / EXEC-* 执行 / DEPLOY-* 部署 / WP-8 订单生命周期验证。

## §1 里程碑总览

| 里程碑 | 核心目标 | 状态 |
|---|---|---|
| M1 底层 | DB/迁移/环境 | 完成 |
| M2 框架与策略 | NT 接入 + 回测策略 | 部分（NT 接入完成；V25 本体+单测落库，回测验证待做） |
| M2.5 数据写入层 | WS->TimescaleDB | post-MVP（非实盘硬前置） |
| M2.7 生命周期验证 | exec_client 闭环 + WP-8 | 全段闭环 |
| M3 执行与安全网 | PREC+RISK+EXEC | 基本全闭环 |
| M4 部署与实盘 | 告警/守护/模拟盘/实盘 | 未开始 |

## §2 M1 底层 — 完成

migration 0001-0011 全 apply；三 hypertable（klines / book_tickers / trades）；compression/retention 配置；NT 1.227；Python 3.12.3。

## §3 M2 框架与策略 — 部分

- NT adapter（Bar/TradeTick）/ exchanges 层（rest/ws/contracts）/ SMA 模板 均完成
- V25 策略本体 + 19 单测完成（commit d049da8，40.md）
- V25 回测验证（方向 A：wp_v25_backtest 真 bar 喂入 BacktestEngine，验 PnL/fills + 对拍基准 清算13+-3/$11288+-5%/胜率77%）待做

## §4 M2.5 数据写入层 — post-MVP

WS->TimescaleDB 三表持续写入 + reconnect + 批量写。表已建、生产写入零代码。
非 MVP 硬前置：策略实盘靠 NT data client 内存喂行情，不经此层；顾问 scoping 明确推迟到实盘后（nice-to-have）。

## §5 M2.7 生命周期 + WP-8 — 全段闭环

LC-A~D（msgbus/cache/instrument/exec_client 生命周期）+ LC-F1（Ed25519 认证）+ LC-L1/L2（teardown）+ WP-8 E0-E3.2（链路->OrderAccepted->cancel->instrument 注入->成交+position/balance->msgbus 事件总线）。

## §6 M3 执行与安全网 — 基本全闭环（v4 最大校正）

### §6.1 PREC 精度
precision.py（commit 3dc0dd6）+ nt_translate.py + nt_submit.py。floor 取整全 Decimal、min_notional、PERCENT_PRICE_BY_SIDE、拒单非夹紧。

### §6.2 RISK 风控（guard.py 五道闸 + 持久化）
killswitch+连亏（SS2.11）-> 日内回撤（SS2.14）-> notional cap（SS2.20）-> balance floor（SS2.23）-> throttle（SS2.24）；持久化 streak/HALTED（SS2.22）+ _daily_pnl 跨重启（44.md，commit 1134720）；file lock（SS2.28）。

### §6.3 EXEC 执行
order_id 幂等+持久化（SS2.12/2.21）/ exec_bridge（PnL+position extractor + 互斥守卫 + post-only 路由 SS2.25）/ exec_reconciler（对账失败 HALT）/ seen_store。

### §6.4 STOP-B testnet 三相真单
Phase 1 cancel（venue 1201712）/ Phase 2 market BUY 成交（1203227）/ Phase 3 market SELL 平仓（1257932），账户回 flat。

### §6.5 b3b-live 生产发单链 + 首单
E2.5-a~b3b-live 整条 live 链 + 首笔 testnet 真单（venue 465632，EXIT_CODE=0，39.md）。

### §6.6 LC 台账 + ce9 五基线
LC-EXEC-1~5 / LC-RISK-1~4 / LC-WS-1 全销账；探针 LC 沿袭 19-23 全关闭（43.md）。
ce9 五基线 md5：guard a0b23f0f（44.md 迁移）/ precision bb0308ce / nt_translate a9cd0219 / nt_submit db974054 / exec_bridge 2a92d362。

## §7 M4 部署与实盘 — 未开始

| 项 | 内容 |
|---|---|
| DEPLOY-告警 | Telegram（PnL/异常/killswitch） |
| DEPLOY-守护 | systemd + 崩溃自动恢复 + 重启拉回仓位 |
| DEPLOY-模拟盘 | 4 周不可压缩日历 |
| DEPLOY-实盘 | 极小额，首周仓位砍半 |

## §8 剩余路径（MVP 实盘前）

- 硬前置：V25 回测验证 + M4 四项 + F 单刀（go-live 前）
- post-MVP / 不挡实盘：M2.5、文档轮（item1/item6）；_daily_pnl（item4）已做

## §9 backlog 现状

| 项 | 状态 |
|---|---|
| item1 CLAUDE-REBUILD-FULL | 文档轮（本轮接续） |
| item6 MasterTracker v4 | 本文件 |
| F nt_translate 接 live + precision 替换 | 单刀，go-live 前必做 |
| nt_translate 分工 | 见 §10 |

item2/3/4/5/7/8 全清（详 41-44.md）。

## §10 nt_translate 分工澄清

- nt_translate.py = PREC 翻译层 (a)：NT Instrument -> InstrumentLimits。当前 src 零外部 caller、test-only，F 待将其接进 live precision 路径。
- nt_order_translate.py = DORMANT 自建 exec 链（a/b1/b3a）：NT Order -> new_order kwargs。live path 走 NT BinanceLiveExecClientFactory，本链未被 cli.py 引用，去留待定（承 43.md SS6.3）。

## §11 关键纪律索引（详见 CLAUDE.md）

双轨制 SS6.4（出题人!=答题人）/ 四类放水 SS6.2 / STOP 红线（B/DOCS/ARCH/VERDICT/NET/SYS）/ 三闸 GATE-1/2/3 / ce9 五基线零漂哨兵 / raw 优于 verdict。
