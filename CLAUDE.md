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

> 注:本文件 §6 验证体系 / §12 双轨制 / §13 终审为本会话(2026-06-01)mini 补全;§4 红线(STOP-* 体系)的完整定义、§1~§5/§8 等章节仍待重建(backlog:CLAUDE-REBUILD-FULL)——其内容在一次未入 git 的 CLAUDE.md 版本(曾达 205 行,见 21.md 记 md5 67f2ae97)丢失中遗失。§6(项目宪章层面)另见 CHARTER.md。

## §6. 验证与防作弊

agent 满足判据时,不得以下列手段「凑过」;复核方对每一轮逐项查。

### §6.2 四类放水(复核必查)

- **改阈值**:把判据里的数值门槛改松(如 timeout、容差、通过率)。
- **删条目**:删掉判据中不利的检查项 / 测试 / 断言。
- **改判据**:重新解释或替换判据措辞,使本不达标变达标。
- **粉饰**:用文字叙述掩盖未达标事实(如把 FALSE 说成 moot / 已豁免 / 不适用)。

四项任一命中即判据放水,该轮不得判 CLEAN。复核方在每轮回传里逐项核「四类放水零命中」。

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

### §10.5 核审三件套(复核方最小证据包)

复核方据以判 verdict 的最小证据包,三件缺一视为不可复核:
1. **完整 run log**:agent 实跑的原始 stdout(文本,非截图、非摘要)。
2. **verdict 逐条 True/False**:每条判据的达标结果,逐条列出。
3. **md5 / 基线快照**:相关产物 md5 + 五基线 md5 实测值,坐实零漂 / 故意改动范围。

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

## §6.6 GATE-1：git 写闸（配置级强制，2026-06-01 落地）

**背景**：§2.29 / 6b10968 / 5b89c66 连续 3 次 STOP-DOCS-SKIP——plan 均写"出预览停住等 go"，工具放行后同轮即把 commit 跑了。结论：靠本文件写规矩拦不住，唯一真闸是把 git 写操作移出 CC 自动执行。

**机制**（用户级 `~/.claude/`，不在本 repo 内，环境重建须重新施加）：
- 主闸：PreToolUse hook `~/.claude/hooks/git-write-gate.sh`（matcher=Bash），命中 git 写动词（add / commit / push / reset / restore / rm / mv / stash / merge / rebase / cherry-pick / revert / tag / clean / pull）即返回 permissionDecision=deny。官方文档：hook 的 deny 连 `--dangerously-skip-permissions` / bypass 都拦得住。
- 闸体指纹（用户级 ~/.claude/，环境重建须重施;SS6.7 启动复验据此核）：git-write-gate.sh md5 = 281c070df935338333d2fb18bfc74976（2026-06-01 绑定;此前本节未记 md5。注:CC memory 中的 ad6b8e17 非本档记录，已 disregard;实测文件 md5 == 交接基线 281c070d，G1 行为复验 deny）。
- 副闸：`~/.claude/settings.json` 的 `permissions.deny`（同上 15 条动词）。deny 清单在 bypass 下会被跳过，故以 hook 为准。
- 读类 git（status / log / diff / show）不拦。

**效果**：CC 物理上无法 git add / commit / push；commit / push 只由主理人手敲。

**验证（GATE-1 CLEAN，复核方 2026-06-01 签）**：deny 清单 15 条；真 commit（`git commit --allow-empty`）被 GIT-WRITE-GATE deny、未执行、HEAD 仍 5b89c66；只读 git 放行、工作树 clean；hook 可执行。dry-run 不充当判据（hook 对 dry-run 与真写可能有差异），故以真 commit + HEAD 未动为铁证。

**两条带走（后续发单闸用）**：
1. hook 是真背板（盖过 bypass），deny 清单是 belt（bypass 下失效）。
2. hook 的 deny 对 MCP 工具调用不生效（claude-code #33106）。若 testnet / live 下单走 MCP 工具而非 Bash 跑 python，此 hook 拦不住，发单闸须另设。

## §6.7 会话启动复验协议（GATE-1 自检，2026-06-01 建立）

**为何**：GATE-1 的闸体（hook + settings.json）在用户级 `~/.claude/`，不随本 repo 走。换机 / 环境重建 / 不同用户 = 闸可能不在。且"配过"不等于"正在拦"（deny 清单会被 bypass 跳过、可能漏到 ask）。故每次新 CC 会话、动任何 git 写相邻的活之前，须以行为方式复验闸仍物理有效。

**何时**：每个新 CC 会话开工前，尤其在任何 docs / commit 工作或 Category B 之前。

**怎么验（决定性、行为级）**：
1. 记基线：`git rev-parse --short HEAD`。
2. CC 尝试真 git 写：`git commit --allow-empty -m GATE_SELFTEST_DROP`。
3. 判定：被 `GIT-WRITE-GATE` deny、未执行、且 HEAD 仍 == 基线 → 闸活，放行；commit 落地 / HEAD 前进 → 闸 down，按下方处置。

**闸 down 处置**：① STOP，任何 git 写相邻工作不准动；② 主理人手敲 `git reset --hard HEAD~1` 丢掉自检空提交；③ 按 §6.6 重新施加 hook + settings；④ 复验通过才继续。

**注**：dry-run（`-n` / `--dry-run`）不充当判据——同 §6.6，须真 commit + HEAD 未动为铁证。


SS6.8 发单闸（GATE-2 / WP-8）  复核方 2026-06-01 签

SS6.8.1 mainnet 硬拦（已建 + 验 CLEAN + 落档）
- 定位：defense-in-depth 一层，非唯一防线。真 backstop 是 config 层默认 TESTNET
  （core/config.py:46 alias，不显式设永远 testnet）。闸只拦"主动把 env 设成 mainnet"
  这个显式误触动作。不给"实盘绝无可能误触"的虚假安全感。
- 闸体（用户级 ~/.claude/，不在 repo、环境重建会丢、须重施）：
  - hook：~/.claude/hooks/mainnet-gate.sh，md5 02ed4b830d12e93aa5968bf09501477e。
    primary grep HERMES_ENV[[:space:]]*=[[:space:]]*['"]?mainnet（-Eiq）
    + belt os.environ['HERMES_ENV']=...mainnet，命中即 permissionDecision=deny。
  - settings：~/.claude/settings.json，md5 b07a03a1cd0df1501eceb6dff81e88df，
    deny 数组 17 条（15 git + 2 mainnet：Bash(HERMES_ENV=mainnet:*) +
    Bash(export HERMES_ENV=mainnet:*)），hooks.PreToolUse[matcher=Bash] 数组双 hook
    （git-write-gate + mainnet-gate，并存非替换）。
- 作用域铁律：hook 只拦 Claude Code 自己的工具调用，拦不了 Iris 裸 shell——
  这是设计本身（写/发单只由 Iris 手敲）。验闸主体必须是 CC，由 Iris 跑必假绿
  （实为闸按设计放行 Iris）。
- 验闸 CLEAN 铁证（CC 主体）：G2 HERMES_ENV=mainnet echo 被 MAINNET-GATE deny、
  echo 未执行、marker 全缺；G1 回归 git commit --allow-empty 仍被 GIT-WRITE-GATE
  deny、HB==HA==8057628；控制组 C1 HERMES_ENV=testnet echo OK 放行、
  C2 grep mainnet 只读放行（不过宽）。
- known limitations（不阻塞，记录在案）：(1) 间接变量 X=mainnet; HERMES_ENV=$X；
  (2) os.putenv/setdefault/update；(3) deny 对 MCP 工具不生效（#33106；当前无 MCP，不适用）。


SS6.8.1-G3 GATE-3 trade-live 发单闸（预埋；能力存在前先建，复核方 2026-06-01 签）
- 定位：守 SS6.8.2(1) 的唯一发单入口 hermes trade-live。在 CLI/exec 层接入前预埋，
  能力一旦出现即被拦。Telegram 仅只读，发单收口到此单一子命令。
- 闸体（用户级 ~/.claude/，不随 repo，环境重建须重施）：
  - hook：~/.claude/hooks/trade-gate.sh，md5 c9c4cbb0daf4299c62c391f26786614c。
    primary grep hermes[[:space:]]+trade-live（-Eiq），命中即 permissionDecision=deny。
  - settings：~/.claude/settings.json 更新为 md5 625c1a96856b32a9c50534f18305c9ef，
    deny 数组 18 条（15 git + 2 mainnet + 1 Bash(hermes trade-live:*)），
    hooks.PreToolUse[matcher=Bash] 三 hook 并存（git-write-gate + mainnet-gate + trade-gate，追加非替换）。
    旧 settings md5 b07a03a1cd0df1501eceb6dff81e88df 已作废，以此为准。
- 验闸 CLEAN 铁证（CC 主体）：G3 hermes trade-live --dry 被 TRADE-GATE deny（非 crash 兜底）；
  G2 回归 HERMES_ENV=mainnet echo 被 MAINNET-GATE deny；G1 回归 git commit --allow-empty
  被 GIT-WRITE-GATE deny、HB==HA==701cae6；控制组 HERMES_ENV=testnet echo OK 放行。
- known limitation：只读里 hermes trade-live 字面串（如 grep）会被误拦，无害，拆串绕过。
- 注：此闸守命令入口；E2.5-a 实现 new_order 时另须确认 new_order 默认 testnet、收口到此入口、
  Telegram 进程不 import 发单路径（SS6.8.2 验收判据）。

SS6.8.2 exec 入口收口硬判据（前瞻；CLI/exec 层未建，落为构建期契约 = E2.5 签 go 前置）
- 证伪铁证：CLI 模块物理不存在 —— ls src/hermes/cli.py + ls src/hermes/cli
  双 No such file or directory；entry point hermes = "hermes.cli:main"
  （pyproject.toml:89）指向缺失模块，hermes 命令启动即崩。框架已选 Click
  （click>=8.1,<9.0，pyproject.toml:58）。当下无任何活发单路径
  （三层证伪：exec node 零命中 -> new_order 桩 -> CLI 缺失）。
- E2.5 接执行层时必须兑现（四条，全绿才签 go）：
  (1) 启动 live/testnet 撮合节点收口到唯一一条 hermes <subcommand>（Click command），无旁路；
  (2) 默认 testnet，mainnet 仅靠显式 HERMES_ENV=mainnet，入口不另引开关；
  (3) 子命令名确定即注册进 PreToolUse Bash hook deny（同机制），真单只由 Iris 手敲；
  (4) 行为级验闸（CC 主体）且不真发单——CC 试跑该启动命令在 exec client 实例化 /
      socket 打开前被 deny。

带走项：
(1) exec 层接入时，把启动子命令名注册进 hook deny + 跑行为级验闸 CLEAN（CC 主体），方可进 STOP-B；
(2) 验闸主体铁律（SS6.8.1）写死，杜绝再用 Iris shell 验闸得假绿；
(3) SS6.6 带走项 2（hook 对 MCP 不生效）当前无 MCP 不适用，未来引入 MCP 发单工具须重评。

## §12. 双轨制(出题人 ≠ 答题人)

本项目核心制衡:verdict 判据的出题权与达标权分离。网页 Claude = 出题人 / 复核方,Claude Code = 答题人 / 执行方,用户 = 终审。§6.4 是本原则的逐轮操作细则;本节是其总原则。任何一方不得同时出题又自判达标。

## §13. 终审归属

某轮是否判定 CLEAN,由用户拍板。网页 Claude 与 Claude Code 意见相左时,用户裁;§4 红线(STOP-* 体系)绝对优先于任何放行。

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

## §8 ce9 受保护文件与五基线哨兵

### §8.1 ce9 五保护文件
下列文件涉及金融正确性核心（CHARTER §5 A 层），未经主理人显式 carve-out 授权
禁止修改（STOP-ARCH，见 §4）：
- src/hermes/risk/guard.py
- src/hermes/execution/precision.py
- src/hermes/execution/nt_translate.py
- src/hermes/execution/nt_submit.py
- src/hermes/execution/exec_bridge.py

### §8.2 五基线 md5 哨兵
tests/unit/execution/test_post_only_routing.py::test_ce9 硬编码五文件 md5，任一漂移
即测试失败，作为"未授权改动"的零漂哨兵。当前基线（承 44.md §6，HEAD d14b6aa）：

| 文件 | md5 |
|---|---|
| guard.py | a0b23f0f9e6a1c910b06ddfd22489bf9 |
| precision.py | bb0308ce6cf0b50f5214e5d9819f2cc8 |
| nt_translate.py | a9cd0219475a99c6b1ea145d4e45f370 |
| nt_submit.py | db974054f08f4a15ee3357cd74a565cb |
| exec_bridge.py | 2a92d362b9b30cdd9d190128fcd1d21d |

授权 carve-out 改动某文件后，须同步迁移其基线 md5（in-place 单行替换）；旧 docs 里
该文件旧 md5 全部作废，以最新 commit + 本节为准。
