# Phase 2.E — Documentation Closeout

目标：把 Phase 2（Binance REST + WS 客户端）的成果文档化，为 Phase 3
TimescaleDB 写入做好接手。**不动 src，不动 tests，纯文档。**

## 范围

1. README.md：补 Hermes AI 项目简介、Phase 1-11 路线图（已在 5f9927c）、
   开发环境快速上手、当前 Phase 2 完成度状态
2. CHANGELOG.md：新建。从 Phase 1 起 backfill 到 Phase 2.D.6-iii 的关键
   commit。格式 Keep-a-Changelog
3. docs/architecture/binance_ws.md：BinanceWsClient 的设计文档
   - 重连状态机（_run_one / _run_with_reconnect 的协作）
   - keepalive（ping_interval=20, ping_timeout=10）
   - WsMetrics 7 字段的语义和监控用法
   - 已知限制（无应用层 ping、无 stall detection——留给子项 3）

## 边界

- 不动 src/、tests/
- 不重写 CLAUDE.md（已经手动改过了）
- 不 commit 任何代码改动，只 commit 文档
- 不"顺手优化"现有文档的措辞
- 子项 3 watchdog stall 在 git stash@{0} 里，不要 apply、不要参考

## 工作粒度

文档分三个独立 commit，按 1→2→3 顺序：
1. docs(readme): expand README with quickstart and phase status
2. docs(changelog): add CHANGELOG.md backfilled to Phase 2.D.6-iii
3. docs(architecture): add binance_ws.md design doc (Phase 2.E)

每个 commit 前给我看：
- git diff --stat
- 文档内容（原始 cat，不要折叠）

每条 commit message 我点 go 你才 commit。