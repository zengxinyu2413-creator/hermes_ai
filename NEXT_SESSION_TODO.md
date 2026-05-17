# NEXT SESSION TODO — Phase 2.D.6-iii (WsMetrics 测试)

## 上一个 session 已完成
- commit 094bb24: WsMetrics frozen dataclass + BinanceWsClient 计数器
- 2 files changed, 76 insertions, 13 deletions
- 已 push 到 origin/main
- 现有 91 个 test_binance_ws.py 测试全绿，未加新测试

## 本 session 要做：给 WsMetrics 加测试

### 1. 新增测试，至少覆盖
- [ ] messages_received_total 在收到 N 帧后等于 N
- [ ] messages_by_kind[kline] 正确递增
- [ ] reconnect_count 在一次断线重连后是 1
- [ ] _current_attempt 在重连成功后归零
- [ ] metrics property 返回的 WsMetrics
cat > NEXT_SESSION_TODO.md << 'TODO_EOF'
# NEXT SESSION TODO — Phase 2.D.6-iii (WsMetrics 测试)

## 上一个 session 已完成
- commit 094bb24: WsMetrics frozen dataclass + BinanceWsClient 计数器
- 2 files changed, 76 insertions, 13 deletions
- 已 push 到 origin/main
- 现有 91 个 test_binance_ws.py 测试全绿，未加新测试

## 本 session 要做：给 WsMetrics 加测试

### 1. 新增测试，至少覆盖
- [ ] messages_received_total 在收到 N 帧后等于 N
- [ ] messages_by_kind[kline] 正确递增
- [ ] reconnect_count 在一次断线重连后是 1
- [ ] _current_attempt 在重连成功后归零
- [ ] metrics property 返回的 WsMetrics 是 frozen（尝试修改字段应报 FrozenInstanceError）
- [ ] messages_by_kind 浅拷贝正确性（外部修改返回的 dict 不影响内部状态）

### 2. 验证
- [ ] pytest --collect-only 确认新增了 X 个测试
- [ ] python -m pytest tests/unit/exchanges/test_binance_ws.py --tb=short 2>&1 | tail -3
      预期 (91 + X) passed，无 failure

### 3. commit + push
- 显式 stage：git add tests/unit/exchanges/test_binance_ws.py
- commit message 用多个 -m，不要粘多行文本进终端

## 踩坑提醒（上个 session 的教训）
- 粘贴 commit message 千万别用多行带 > 的格式，会被 shell 当命令执行并误建文件
- 用 git commit -m "..." -m "..." -m "..." 多段拼接
- core.pager 已设为 cat，git diff 不再分页
