# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Setup (Python 3.11.15 required — enforced by .python-version)
pyenv local 3.11.15
python -m venv venv && source venv/bin/activate
pip install -e ".[dev]"

# Run all tests
pytest

# Run a single test file
pytest tests/unit/exchanges/test_binance_ws.py

# Run a single test by name
pytest tests/unit/exchanges/test_binance_ws.py::TestStreamsValidation::test_empty_list_rejected

# Lint
ruff check src tests

# Format
ruff format src tests

# Type check
mypy src/hermes
```

## Environment

Copy `.env.example` to `.env` before running anything. `HERMES_ENV` defaults to `testnet` — switching to `mainnet` (real money) requires an explicit `HERMES_ENV=mainnet`. All env vars are prefixed `HERMES_` except the Binance key pairs (`BINANCE_<ENV>_API_KEY` / `BINANCE_<ENV>_API_SECRET`).

## Architecture

### Configuration layer (`src/hermes/core/`)

`HermesConfig` (pydantic-settings) is the single config object per process. Build it once at startup with `HermesConfig.from_env()`. Nothing else reads `os.environ` directly. `BinanceCredentials` is a separate model so credentials can be passed around without dragging unrelated config; access them via `config.credentials` (lazy property, not a stored field).

All exceptions inherit from `HermesError` (`core/exceptions.py`). Subtree: `BinanceError → BinanceAPIError → RateLimitError`, plus `ConfigurationError`, `OrderError`, `SigningError`.

### Exchange layer (`src/hermes/exchanges/`)

Responsibility is split across four files:
- `_signing.py` — pure HMAC-SHA256 signing, no I/O.
- `binance_credentials.py` — `BinanceCredentials` + `BinanceEnvironment` enum.
- `binance_contracts.py` — typed data contracts: `Kline`, `BookTicker`, `Trade`, `StreamMessage`, `StreamKind`. All prices and volumes use `Decimal`, not `float`. These are frozen dataclasses with `slots=True` (immutable, hashable, memory-efficient for backtest volumes). The rest of the codebase never touches raw Binance JSON — it always receives one of these typed objects.
- `binance_ws.py` — `BinanceWsClient`: async context manager for Binance combined-stream WebSockets. Streams are fixed at construction; construction itself is event-loop-free (queue is created in `__aenter__`). `_run_with_reconnect` wraps `_run_one` in an infinite loop with exponential backoff + jitter; `_run_one` does the actual `websockets.connect`. Consumers call `async for msg in ws.stream()` and receive `StreamMessage` envelopes. `_parse_message` never raises — malformed frames produce `StreamKind.UNKNOWN`.
- `binance_rest.py` — `BinanceRestClient`: httpx async client.

### Module status

`src/hermes/regime`, `strategies`, `risk`, `execution`, `orchestrator`, `monitoring`, and `backtest` are stubs — they contain only `__init__.py`. Active development is in `exchanges`.

### Test layout

```
tests/unit/        # fast, no I/O — mock network in WS tests
tests/integration/ # requires running services (DB, Redis)
tests/e2e/         # full stack
```

`asyncio_mode = "auto"` in `pyproject.toml` — all `async def` test functions are treated as coroutines automatically; no `@pytest.mark.asyncio` needed. `pythonpath = ["src"]` means imports are `from hermes.exchanges...`, not `from src.hermes...`.

## Key conventions

- Line length: 100 (ruff `E501` is ignored — long lines allowed).
- Ruff rule set: `E, F, I, N, W, UP, B, SIM, RUF`.
- Mypy runs in `strict` mode over `src/hermes` only.
- Stream names passed to `BinanceWsClient` must have lowercase symbol parts (`solusdt@kline_1m`, not `SOLUSDT@kline_1m`) — Binance silently drops incorrectly-cased subscriptions.
- `Kline.from_binance_ws_payload` accepts the inner `k` dict, not the outer event — the WS client unwraps before calling.
- 会话窗口结束（额度耗尽 / session reset / 主动关闭）= 工作流程暂停。
  重置后开新会话时，第一条消息必须是人明确说"做什么 + 不许做什么"。
  PHASE_2D6_HANDOFF.md、SESSION_NOTES.md、README 路线图是参考资料，
  不是任务清单。AI 不许把它们当 todo 自驱推进。
- 重要确认（"是否 commit"、"是否进入下一子项"、"是否动 src"）必须由
  人显式说"yes"或"go"。AI 一旦看到 working tree 干净就自动推进下一个
  任务是禁止的。

> 注:本文件与 CHARTER.md 共同构成项目方法论。未在本文件定义的节号——§4(红线)、§6 等——见 CHARTER.md 对应章节。§6.2(四类放水=改阈值/删条目/改判据/粉饰)、§10.5(核审三件套)、§12/§13 的正式定义文本,在一次未入 git 的 CLAUDE.md 版本(曾达 205 行,见 21.md §2.x 记 md5 67f2ae97)丢失中遗失;其含义沿历史销账惯例使用,正式定义待重建补全(backlog:CLAUDE-REBUILD)。

## §6.4 verdict 判据的双人分离原则(出题人 ≠ 答题人)

背景:用户不读代码,核心制衡依赖网页 Claude。为防止 agent
"自己定标准 / 自己达标 / 自己宣布通过"(§6 要堵的核心洞),
本节规定 verdict 判据的出题权与达标权必须分离。

### §6.4.1 判据来源

- 每一轮(E3.2 及之后)的 verdict PASS/FAIL 条件,由网页 Claude
  出草案,经用户转交后,作为 agent 必须满足的【硬判据】。
- agent 收到硬判据后,职责仅限于:写脚本满足它 / 收集证据 / 跑出
  逐条结果。agent 【不得】自行新增、删除、放宽或重新解释判据。
- 若 agent 认为判据有误或不可达,必须按 §6.2 显式申报并 STOP 回
  用户,不得静默调整,也不得"为了跑通"私自改判据。

### §6.4.2 证据回传

- 跑完后 agent 必须按 §7 / §8 把【完整】证据回传:核审三件套
  (§10.5)、完整 run log、verdict 逐条 True/False。
- 这些必须是【文本】,不是截图。截图无法逐字核对判据是否被改,
  视为未提供有效证据。

### §6.4.3 复核与终审

- 用户将 agent 回传的证据转交网页 Claude,由网页 Claude 对照
  自己出的判据复核,重点查 §6.2 四类放水(改阈值 / 删条目 /
  改判据 / 粉饰)及 tie-back 是否对上。
- 网页 Claude 的复核结论【不是终审】。它只能做不依赖跑代码的
  逻辑层审查:判据有没有被动、证据与结论是否自洽、有无跳步粉饰。
  它【无法】保证脚本真在机器上跑过、testnet 真扣过余额——
  那个物理事实只有 agent 的 run log 体现,网页 Claude 只能假定
  log 未经伪造。因此核审三件套与完整 run log 是唯一抓手,缺一律
  视为不可复核。
- 最终是否判定该轮 CLEAN,由【用户】拍板。网页 Claude 与 agent
  意见相左时,承 §12 / §13:用户裁,§4 红线绝对优先。
- 复核方退回/驳回 agent 已报 CLEAN 或已销账的项时,必须基于 run log / md5 / git 等实测证据,不得凭 prose 印象或记忆驳回。与本节"复核非终审"并行:复核方既不能凭印象判 PASS,也不能凭印象判 FAIL(CL2)。

## §6.5 方法论教训（历史积累）

### 教训 CB1（PREC 阶段，2026-05-27）

判据修订必须走"正式修订 + 用户拍板"；agent 发现判据自相矛盾时，应 STOP-VERDICT
上报，不得自行消解或放宽判据措辞。

### 教训 CR7（RISK 阶段，2026-05-28）

用 grep 当"越界探针"的判据，存在误伤注释/docstring 的先天问题。出题时应加豁免子
句："docstring/注释中作为范围声明的命中，经复核可豁免"；答题时若 grep 命中是文档
性内容，应保留 docstring 并在 run log 说明无害，不应删行迎合 grep。

### 教训 CR8（RISK 阶段，2026-05-28）

判据出题前，baseline 测试数必须 `pytest -q` 实测取真值，不许凭文档抄数字——文档
快照会过时。起手核对清单必加：`pytest tests/unit/ -q` 取当前真 baseline，作为本
轮零回归基准。出题人同样对出题质量负责。



### 教训 EXEC-DRIFT（EXEC 阶段，2026-05-28）

网页 Claude 出指令包后切话题前，必须明确确认：(a) 该指令是否已转发给 Claude Code；(b) 若已转发，是否已放行/执行。无此确认时，后续看到"已完成"报告应先怀疑自身记忆漏洞，凭证据（file md5/timestamp/git log）裁定，不预设违规。本会话发生过一次：网页 Claude 出 EXEC 实现指令后切到 Plan-Mode 落档话题，未跟踪指令转发状态，后看到 Claude Code 报"EXEC 已实现"误触发 STOP-VERDICT，经证据核实属流程信息流脱节；Claude Code 双 CB1 应用（不自行裁定 A/B，要求用户二选一明确）防住了潜在的"被误判后强行回滚正确产物"风险，记正面教训。
### 教训 PHASE3-RECONCILE（STOP-B Phase 3，2026-05-30）

NT portfolio reconcile 失效（synth_order 未到 ACCEPTED 状态时，OrderFilled 被 exec_engine 静默丢弃，net_position 不更新）时，可直接向 NT cache 注入合成 Position 作 workaround。但注入后「fill.qty == pre_close_net」等式成构造性永真，不构成对真实持仓验证，必须三段诚实标注并将验证力显式落到 post_net==0。附正面教训：abort 闸（pre_close_net != 预期值即 disconnect）在干跑中成功拦住了 NT net=0 时误发 SELL 变开空的灾难，abort 闸设计值得保留。
### 教训 STOP-DOCS-SKIP（落档绕过预览先行，2026-05-31）

LC-EXEC-2 落档（21.md §2.25）写入时，Claude Code 把网页 Claude 给出的「§2.25 内容规格 + 三条诚实标注」当成放行，直接 Edit 追加进 21.md——跳过 STOP-DOCS 预览先行全流程：无预览回传给复核方过眼、无主理人 go、无写前干跑，并破了该 PLAN 自检「无对 docs/handoffs/*.md 改动: 是」一条。事后 H1~H3 只读自校（md5 / wc / §2.25 唯一 / 污染探针 / 三标注在位 / git untracked）补证正文 CLEAN，承 EXEC-DRIFT 不回滚，记 [STOP-DOCS-SKIP]。

规矩（硬性，承 §4 红线 + §7.5 STOP 先于 Plan）：复核方给出落档内容规格 ≠ 放行。STOP-DOCS（写 docs/handoffs/*.md 或 CLAUDE.md）顺序不可压并、不可跳：CC 干跑预览（cp/拼接现网为底）→ 回传预览全文 + md5 + wc + 污染探针 → 复核方过眼 → 主理人在 chat 里显式 go → 才写入 → 写后 md5/wc/grep 自校。"内容已给"/"规格已定" 绝不充当 go。PHASE 2 必须 cp 已过眼的 /tmp 预览，不可用 Edit 重做插入（会让写后 md5 ≠ 预览 md5，毁掉『预览==写入』坐实）。

### 教训 FALSIFY-CLEAN（证伪场景双轨制有效性，2026-05-31）

LC-EXEC-3 收口为「证伪调查」——这类任务最易把不方便的 FALSE 粉饰成 moot 清账。本轮 CC 在 FV4 该 FALSE 报 FALSE、沿 F4/F5 追到 manager.pyx 单/多币种分叉、两个未实测点（base/quote commission、multi_currency 分支）硬留账不圆，未触 §6.2 四类放水。佐证：出题人/答题人分离（§6.4）+ 四类放水探针组合，在「证伪」场景下与「实现」场景同样有效。

配套防呆（硬性）：证伪判据须由出题人预先定死 FV 条件（全 True 才证伪成立），杜绝答题人事后凑 moot。证伪不成立（任一 FV=False/UNKNOWN）须如实转实修或记账，不得为「清雷」反推 moot。

## §7. Plan-Mode 协作协议(减少弹窗打断,**不**降低安全网)

### §7.1 适用与不适用

**适用**:用户给 Claude Code 一个"任务包"(本项目典型形态:网页 Claude 出的多步指令清单,如 §0 起手核对 / 子任务侦察 / 一刀实现)。

**不适用**(强制走原逐项 Yes 流程,Plan-Mode 失效):
- 任何 STOP 触发的操作:STOP-NET / STOP-B / STOP-DOCS / STOP-SYS / STOP-VERDICT / STOP-ARCH
- 用户在 chat 里没明确说"go this plan" 或等价(中文"按 plan 跑"/"go"/"批量执行 plan")
- 用户的指令本身就是单步而非任务包

### §7.2 Plan 块的强制格式

Claude Code 在 ACK 之后、第一次调用工具之前,必须输出一个 `[PLAN]` 块,结构如下:
[PLAN]
任务总览: <一句话总结这一轮要干什么>
预计步骤数: <N>
STOP 触发判定: <NONE / STOP-XXX(具体类别)>
预计写入文件: <列具体路径,只读步骤写 "无">
预计跑测试: <是/否,若是说大致命令>
预计耗时: <粗估,如 "5 分钟" / "30 分钟">
逐步清单:
Step 1: <命令或工具调用> — <一句话目的>
Step 2: ...
...
Step N: <最后一步,如回传 run log>
红线复核(Claude Code 自检):

无 git add/commit/push: 是/否
无 pip install / .env / .gitignore 改动: 是/否
无对 docs/handoffs/*.md / CLAUDE.md 改动: 是/否
无外网调用 / testnet 连接: 是/否
无 src/hermes/risk/guard.py、precision.py、nt_translate.py、nt_submit.py 改动: 是/否(零回归基线)

等用户在 chat 里回 "go this plan" 或等价后批量执行。
[/PLAN]

### §7.3 用户拍板与放行语义

- 用户在 chat 里回 "go this plan" / "go" / "按 plan 跑" / "执行" / 同类肯定语 → Claude Code 可以**一口气**跑完 Plan 内所有步骤,**不为白名单内命令再单独弹 chat 询问**(工具权限弹窗由本地配置决定,本协议不替它决策)
- 用户要求微调("第 3 步换成 X"/"跳过第 5 步")→ Claude Code 回新版 Plan 块,等再次拍板,**不**部分执行
- 用户回"不"/"停" → 全部取消,不执行任何 Step

### §7.4 Plan 执行中的中断条件(任一触发,立即停下报上来)

- 任一 Step 报错(非预期返回值、命令失败、文件不存在)
- 任一 Step 的实际副作用超出 Plan 声明范围(如声明只读但实际产生写入)
- 中途发现需要新增不在 Plan 内的 Step(如 grep 结果显示需要补侦察)
- 任一 Step 即将触发 STOP 类红线(即便 Plan 自检漏判)

触发后:停止后续 Step,贴当前进度 + 中断原因 + 建议下一步,**等用户重新拍板**。**禁止** Claude Code 自己加 Step 续跑。

### §7.5 与既有 STOP 红线、§6.4 出题人/答题人分离、§6.5 教训的关系

- Plan-Mode **不**改 STOP 红线优先级:STOP 永远先于 Plan 放行
- Plan-Mode **不**改 §6.4 双轨制:网页 Claude 仍是判据出题人,Claude Code 仍是答题人;Plan 块替换的只是"逐项 chat 询问 → 一次性 plan 询问"
- Plan-Mode **不**豁免 §6.5 三条教训:CR7(grep 误伤 docstring 不删行)、CR8(baseline 实测不抄)、CB1(出题人改判据须正式修订)在 Plan 内每个 Step 仍然适用
- 用户保留随时打断的权利,Claude Code 不得以"Plan 已放行"为由拒绝中途打断

### §7.6 [PLAN] 先行硬约束（承 EXEC-DRIFT，2026-05-28 连续两次跳过补强）

Plan-Mode 任务包：执行方（Claude Code）收到后，第一个输出块必须是 [PLAN]；在 [PLAN] 获 "go this plan"（或等价）放行前，禁止任何文件写入 / 脚本改动 / 测试执行。

违反时：该次产物不强制回滚（避免 EXEC-DRIFT 式"回滚正确产物"），但必须在落档中显式标注 [PLAN-SKIP]，并事后补一份 PLAN 复盘（列出本应声明的步骤 / STOP 判定 / 写入清单）。

与 §7.1 关系：本条是 §7.1 "ACK 后、首次调用工具前必出 [PLAN]" 的强制化——把"应当"升为"硬门禁 + 违规留痕"。本条不豁免任何 STOP 红线，STOP 永远先于 Plan 放行（承 §7.5）。
