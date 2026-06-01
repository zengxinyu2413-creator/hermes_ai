# WP-8 E0 — 下单链路地图(侦察定稿)

> 生成时间:2026-05-26 基线(WP-7 三件套闭环后)
> 性质:纯只读 grep + sed 实证产出,零网络动作。NT 版本 1.227,spot 路径。
> 口径决断:**A(throwaway 探针)** —— E1–E3 在 `experiments/m3_probe/` 里跑,testnet only + 合规小单,验证"NT submit→report 链路通不通",**不等于** M3 的 EXEC/PREC/RISK 生产模块。

---

## 1. 链路全图

\`\`\`
┌─ 下单路径(REST,同步知道接受/拒绝)──────────────────────┐
│ OrderFactory.limit/market   common/factories.pyx:312 / :236   ← 构造 order
│   │
│ submit_order(SubmitOrder)   live/execution_client.py:277       ← 入口(基类)
│   │
│ _submit_order → _submit_order_inner   binance/execution.py:792 / :799
│   ├─ order.is_closed?            → warning + return(不发单)
│   ├─ _extract_price_match()      → ValueError → _deny_order_pre_submit
│   ├─ _validate_order_pre_submit() → error → _deny_order_pre_submit  ← NT 内建精度/filter 闸口
│   ├─ generate_order_submitted()  → OrderSubmitted 事件
│   ├─ retry_manager.run → account.new_order (http/account.py:620)    ← REST POST
│   └─ REST 拒 → generate_order_rejected(含 -5022 POST-ONLY 特判)
└──────────────────────────────────────────────────────────────────┘
            ╎ (订单进交易所,回报异步走 WS user data stream)
┌─ 回报路径(WS,异步)──────────────────────────────────────┐
│ _handle_execution_report   binance/spot/execution.py:253          ← WS 回报入口
│   │ (dispatch table: BinanceSpotEventType.executionReport → 此函数, :135)
│ handle_execution_report    binance/spot/schemas/user.py:207 (C901 too complex)
│   ├─ client_order_id 解析:CANCELED 用 \`C\`(原单 ID),其他用 \`c\`
│   ├─ strategy_id is None? → 陌生订单路径:parse_to_order_status_report + return
│   │                          (不发 Accepted/Filled 事件)
│   ├─ x==NEW       → generate_order_accepted
│   ├─ x==CANCELED  → (C 字段取原始 client_order_id)
│   └─ x==TRADE / CALCULATED → generate_order_filled
│        └─ 边界:L==0 警告 / EXPIRED 特判 / liquidation(CALCULATED)
│        → evt_queue → cache / portfolio 更新
└──────────────────────────────────────────────────────────────────┘
\`\`\`

## 2. 关键发现

1. **下单 REST、回报 WS,两条分离异步路径** —— 契合段 D 的 IDLE 结构(IDLE 期间等回报)。
2. **NT 内建 pre-submit 校验**(\`_validate_order_pre_submit\`,execution.py:813 附近):不合规单本地 deny,不发网络请求。这覆盖了 PREC 的一部分(精度/filter),但 **不覆盖 RISK**(单笔限额/日亏熔断)—— killswitch 完全是项目自己的责任。这是口径 A 成立的核心证据:探针下单受 NT 精度保护,testnet 合规小单风险可控。
3. **\`handle_execution_report\` 是 C901 too complex** —— NT 自认状态翻译复杂,E3 成交回报真凶概率最高。

## 3. 各段插桩点 + 真凶预判

| 段 | 验证目标 | 插桩点 | 真凶预判 |
|---|---|---|---|
| E1 | 下单 + OrderAccepted 回报 | 下单后扫 cache order 状态 + 等 WS \`x==NEW\` | strategy_id 没绑 → 走陌生订单路径(只发 status report);NT pre-submit deny(精度) |
| E2 | 撤单 + OrderCanceled 回报 | cancel 后等 \`x==CANCELED\`,注意 \`C\` 取原单 ID | cancel 的 client_order_id 双字段坑(\`c\` vs \`C\`) |
| E3 | 成交 + OrderFilled + position/balance | 市价单后等 \`x==TRADE\`,扫 portfolio/account | C901 内 TRADE 分支:L==0 / EXPIRED / position 开仓 / balance 变动 |

## 4. OrderFactory 可用构造(factories.pyx)

\`market\`(:236)、\`limit\`(:312)、stop_market(:417)、stop_limit(:520)、market_to_limit(:637)等。
E1 用 \`limit\`(挂远端不成交),E3 用 \`market\`(立即成交)。

## 5. 实现细节待解(E1 起手时处理)

- 段 D 是裸 exec_client,没有 strategy。OrderFactory 通常由 strategy 持有 → E1 需手动构造 factory + 绑一个 strategy_id 进 cache,否则回报走"陌生订单"路径(发现 #2 的 strategy_id is None 分支)。
- instrument precision 来源:\`_validate_order_pre_submit\` 依赖 instrument 已注册(段 C/D 的 instrument 注入链)。E1 复用段 D 的 instrument。
