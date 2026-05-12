"""
Hermes v5-Turbo  (EMA20/60 + 15m/1H 双周期 + 50%仓 + 4%止损)
================================================================
适配 Nautilus Trader 1.226.0

v5 相对 v2-5x 的变更:
  1. EMA 50/200 → 20/60 (信号频率 ×4-6)
  2. 新增 15min Bar 订阅 → 双周期确认:
     - 1H EMA20/60 判断趋势大方向
     - 15min bar close 作为精细入场触发
     - 15min ATR20 > ATR60 作为波动率过滤 (更短周期更灵敏)
  3. 仓位: 4%风险倒推 → 直接 50% 保证金开仓 (每笔盈亏放大)
  4. 止损: -12% 全平 → -4% 全平, -2% 砍半 (快速止损释放资金)
  5. 止盈收紧匹配: +2% / +4% / +8%
  6. 允许多空双向, 趋势反转时先平后反手
  7. 取消马丁加仓
  8. 保留: ATR 动态杠杆, L2 隔夜, L3 三级熔断, 三级提款

杠杆: 5x
信号逻辑:
  1H bar:  更新 EMA20/60 趋势方向
  15m bar: 当 1H 趋势已确立 + 15m ATR 活跃 → 在 15m close 价格开仓
  这样既有 1H 的方向稳定性, 又有 15min 的入场精度
"""

from datetime import datetime, timezone
from typing import Optional

from nautilus_trader.config import StrategyConfig
from nautilus_trader.indicators import AverageTrueRange, ExponentialMovingAverage
from nautilus_trader.model.book import OrderBook
from nautilus_trader.model.data import Bar, BarType, OrderBookDeltas, TradeTick
from nautilus_trader.model.enums import (
    AggressorSide,
    BookType,
    OrderSide,
    PositionSide,
)
from nautilus_trader.model.events import PositionChanged, PositionClosed
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Quantity
from nautilus_trader.trading.strategy import Strategy


# =============================================================================
# Config
# =============================================================================
class HermesV5TurboConfig(StrategyConfig, frozen=True):
    instrument_id: str = "SOLUSDT-PERP.BINANCE"

    # 双周期 Bar
    bar_type_1h: str = "SOLUSDT-PERP.BINANCE-1-HOUR-LAST-EXTERNAL"
    bar_type_15m: str = "SOLUSDT-PERP.BINANCE-15-MINUTE-LAST-EXTERNAL"

    book_depth: int = 10

    # ── 杠杆 ────────────────────────────────────────────────
    base_leverage: float = 5.0
    min_leverage: float = 2.0

    # ── EMA 趋势 (1H 周期, 20/60) ─────────────────────────
    ema_fast_period: int = 20
    ema_slow_period: int = 60

    # ── ATR 波动率过滤 (15min 周期, 更灵敏) ───────────────
    atr_short_period: int = 20
    atr_long_period: int = 60

    # ── 仓位: 直接 50% 保证金, 无马丁 ────────────────────
    max_margin_usage_pct: float = 0.50
    min_notional: float = 5.0

    # ── 止损 (收紧) ─────────────────────────────────────────
    sl_halve_pct: float = 0.02    # -2% 砍半
    sl_full_pct: float = 0.04     # -4% 全平

    # ── 止盈 (匹配收紧的止损) ──────────────────────────────
    tp1_pct: float = 0.02         # +2% 减 30%
    tp2_pct: float = 0.04         # +4% 减 30%
    tp3_pct: float = 0.08         # +8% 全平

    # ── 微观结构 (回测关闭) ────────────────────────────────
    ob_imbalance_ratio: float = 0.0

    # ── L2 隔夜 (北京 23:00 = UTC 15:00) ─────────────────
    enable_overnight_cap: bool = True
    overnight_cutoff_hour_utc: int = 15
    overnight_max_margin_pct: float = 0.50

    # ── L3 三级熔断 ─────────────────────────────────────────
    daily_loss_halt_pct: float = 0.06
    consecutive_losses_halt: int = 4
    drawdown_halve_pct: float = 0.15
    drawdown_lower_risk_pct: float = 0.30
    drawdown_full_halt_pct: float = 0.50

    # ── 提款阶梯 ────────────────────────────────────────────
    tier1_max: float = 8_000.0
    tier2_max: float = 20_000.0
    tier1_withdraw_ratio: float = 0.0
    tier2_withdraw_ratio: float = 0.30
    tier3_withdraw_ratio: float = 0.50
    pause_withdraw_drawdown_pct: float = 0.20
    tier3_max_drawdown_pct: float = 0.25
    tier_demote_threshold: float = 6_000.0


# =============================================================================
# Strategy
# =============================================================================
class HermesV5Turbo(Strategy):

    def __init__(self, config: HermesV5TurboConfig) -> None:
        super().__init__(config)
        self.cfg = config

        self.instrument_id = InstrumentId.from_str(config.instrument_id)
        self.bar_type_1h = BarType.from_str(config.bar_type_1h)
        self.bar_type_15m = BarType.from_str(config.bar_type_15m)
        self.instrument = None

        # ── 仓位状态 ──────────────────────────────────────────
        self.tp_step: int = 0
        self.risk_locked: bool = False
        self.current_side: Optional[str] = None

        # ── 趋势 (1H EMA 驱动) ───────────────────────────────
        self.trend_direction: int = 0   # +1 多, -1 空, 0 盘整

        # ── 波动率 (15min ATR 驱动) ──────────────────────────
        self.volatility_active: bool = False

        # ── 指标: 1H 周期 ────────────────────────────────────
        self.ema_fast = ExponentialMovingAverage(config.ema_fast_period)
        self.ema_slow = ExponentialMovingAverage(config.ema_slow_period)

        # ── 指标: 15min 周期 ─────────────────────────────────
        self.atr_short_15m = AverageTrueRange(config.atr_short_period)
        self.atr_long_15m = AverageTrueRange(config.atr_long_period)

        # ── 微观结构 ──────────────────────────────────────────
        self.cvd_since_low: float = 0.0
        self.top_bid_vol: float = 0.0
        self.top_ask_vol: float = 0.0

        # ── 风控 ──────────────────────────────────────────────
        self.pause_open_until_bar: int = 0
        self.bar_counter_15m: int = 0
        self.daily_loss_halted_date: Optional[str] = None

        # ── PnL ───────────────────────────────────────────────
        self.consecutive_losses: int = 0
        self.last_realized_pnl: float = 0.0

        # ── 高水位 ────────────────────────────────────────────
        self.equity_high_water: float = 0.0
        self.daily_anchor_equity: float = 0.0
        self.daily_anchor_date: Optional[str] = None

        # ── 提款 ──────────────────────────────────────────────
        self.current_withdraw_tier: int = 1
        self.monthly_pnl_history: list[float] = []
        self.last_month_anchor: Optional[str] = None
        self.month_start_equity: float = 0.0
        self.cumulative_withdrawn: float = 0.0

        # ── L3 动态参数 ───────────────────────────────────────
        self.effective_margin_cap_pct: float = self.cfg.max_margin_usage_pct

    # =========================================================================
    # Lifecycle
    # =========================================================================
    def on_start(self) -> None:
        self.instrument = self.cache.instrument(self.instrument_id)
        if self.instrument is None:
            self.log.error(f"Instrument not found: {self.instrument_id}")
            self.stop()
            return

        self.log.warning(
            f"⚠️  请确认账户杠杆已预设为 {self.cfg.base_leverage:.0f}x"
        )

        # 订阅双周期 Bar
        self.subscribe_bars(self.bar_type_1h)
        self.subscribe_bars(self.bar_type_15m)
        self.subscribe_trade_ticks(self.instrument_id)
        self.subscribe_order_book_deltas(
            instrument_id=self.instrument_id,
            book_type=BookType.L2_MBP,
            depth=self.cfg.book_depth,
        )

        # 1H Bar → EMA
        self.register_indicator_for_bars(self.bar_type_1h, self.ema_fast)
        self.register_indicator_for_bars(self.bar_type_1h, self.ema_slow)

        # 15min Bar → ATR
        self.register_indicator_for_bars(self.bar_type_15m, self.atr_short_15m)
        self.register_indicator_for_bars(self.bar_type_15m, self.atr_long_15m)

        equity = self._equity()
        self.equity_high_water = equity
        self.daily_anchor_equity = equity
        self.month_start_equity = equity

        self.log.info(
            f"🚀 Hermes v5-Turbo 启动 — "
            f"EMA{self.cfg.ema_fast_period}/{self.cfg.ema_slow_period}(1H) + "
            f"ATR{self.cfg.atr_short_period}/{self.cfg.atr_long_period}(15m) | "
            f"50%仓 | SL-4% | TP+2/4/8%"
        )

    def on_stop(self) -> None:
        self.unsubscribe_bars(self.bar_type_1h)
        self.unsubscribe_bars(self.bar_type_15m)
        self.unsubscribe_trade_ticks(self.instrument_id)
        self.unsubscribe_order_book_deltas(self.instrument_id)
        self.log.info(f"📦 停止 | 累计提款={self.cumulative_withdrawn:.2f}")

    def on_reset(self) -> None:
        self._reset_position_state()

    # =========================================================================
    # Bar Handler — 1H: 趋势方向 | 15min: 精细入场触发
    # =========================================================================
    def on_bar(self, bar: Bar) -> None:
        bar_dt = datetime.fromtimestamp(bar.ts_event / 1e9, tz=timezone.utc)
        bar_type_str = str(bar.bar_type)

        # ── 判断是 1H 还是 15min bar ─────────────────────────
        if "1-HOUR" in bar_type_str:
            self._on_bar_1h(bar, bar_dt)
        elif "15-MINUTE" in bar_type_str:
            self._on_bar_15m(bar, bar_dt)

    def _on_bar_1h(self, bar: Bar, bar_dt: datetime) -> None:
        """1H Bar: 更新 EMA 趋势方向 + 日月切换 + 隔夜检查。"""
        self._check_day_rollover(bar_dt)
        self._check_month_rollover(bar_dt)

        if (self.cfg.enable_overnight_cap
                and bar_dt.hour == self.cfg.overnight_cutoff_hour_utc):
            self._enforce_overnight_cap()

        self._evaluate_withdrawal_tier()

        if not (self.ema_fast.initialized and self.ema_slow.initialized):
            return

        # 更新趋势方向
        if self.ema_fast.value > self.ema_slow.value:
            self.trend_direction = 1
        elif self.ema_fast.value < self.ema_slow.value:
            self.trend_direction = -1
        else:
            self.trend_direction = 0

    def _on_bar_15m(self, bar: Bar, bar_dt: datetime) -> None:
        """15min Bar: ATR 波动率过滤 + 精细入场/止盈/止损。"""
        self.bar_counter_15m += 1

        if not (self.atr_short_15m.initialized and self.atr_long_15m.initialized):
            return

        # 更新波动率状态
        self.volatility_active = self.atr_short_15m.value > self.atr_long_15m.value

        # ── 交易逻辑 (15min 驱动) ────────────────────────────
        bar_close = float(bar.close)
        position = self._get_open_position()

        if position is not None:
            pos_side = position.side

            # 趋势反转 → 平仓 + 可能反手
            need_reverse = (
                (pos_side == PositionSide.LONG and self.trend_direction == -1)
                or (pos_side == PositionSide.SHORT and self.trend_direction == 1)
            )
            if need_reverse:
                self.log.info(
                    f"🔄 1H EMA 反转 → 平 {pos_side}"
                )
                self.close_position(position)
                self._reset_position_state()
                if self.volatility_active and self.trend_direction != 0:
                    self._try_open(bar_close)
                return

            # 正常风控 + 止盈
            roi = self._calc_roi(bar_close, position)
            if self._check_risk_control(roi, position):
                return
            self._check_take_profit(roi, position)
        else:
            # 无仓位: 双重过滤后开仓
            if self.trend_direction != 0 and self.volatility_active:
                self._try_open(bar_close)

    # =========================================================================
    # OrderBook
    # =========================================================================
    def on_order_book_deltas(self, deltas: OrderBookDeltas) -> None:
        book: Optional[OrderBook] = self.cache.order_book(self.instrument_id)
        if book is None:
            return
        bid_levels = book.bids()[: self.cfg.book_depth]
        ask_levels = book.asks()[: self.cfg.book_depth]
        self.top_bid_vol = sum(float(lvl.size) for lvl in bid_levels)
        self.top_ask_vol = sum(float(lvl.size) for lvl in ask_levels)

    # =========================================================================
    # Trade Tick — 实盘 tick 级风控
    # =========================================================================
    def on_trade_tick(self, tick: TradeTick) -> None:
        price = float(tick.price)
        qty = float(tick.size)

        if tick.aggressor_side == AggressorSide.BUYER:
            self.cvd_since_low += qty
        elif tick.aggressor_side == AggressorSide.SELLER:
            self.cvd_since_low -= qty

        position = self._get_open_position()
        if position is None:
            return
        roi = self._calc_roi(price, position)
        if self._check_risk_control(roi, position):
            return
        self._check_take_profit(roi, position)

    # =========================================================================
    # 账户
    # =========================================================================
    def _equity(self) -> float:
        if self.instrument is None:
            return 0.0
        account = self.portfolio.account(self.instrument.venue)
        if account is None:
            return 0.0
        bal = account.balance_total(self.instrument.quote_currency)
        return float(bal) if bal is not None else 0.0

    def _used_margin(self) -> float:
        position = self._get_open_position()
        if position is None:
            return 0.0
        notional = float(position.quantity) * float(position.avg_px_open)
        return notional / max(self.cfg.base_leverage, 1.0)

    def _drawdown_pct(self) -> float:
        equity = self._equity()
        if self.equity_high_water <= 0:
            return 0.0
        return max(0.0, (self.equity_high_water - equity) / self.equity_high_water)

    def _daily_pnl_pct(self) -> float:
        if self.daily_anchor_equity <= 0:
            return 0.0
        return (self._equity() - self.daily_anchor_equity) / self.daily_anchor_equity

    def _calc_roi(self, price: float, position) -> float:
        avg_px = float(position.avg_px_open)
        if avg_px <= 0:
            return 0.0
        if position.side == PositionSide.LONG:
            return (price - avg_px) / avg_px
        elif position.side == PositionSide.SHORT:
            return (avg_px - price) / avg_px
        return 0.0

    # =========================================================================
    # 日 / 月
    # =========================================================================
    def _check_day_rollover(self, bar_dt: datetime) -> None:
        today = bar_dt.strftime("%Y-%m-%d")
        if self.daily_anchor_date != today:
            self.daily_anchor_date = today
            self.daily_anchor_equity = self._equity()
            if self.daily_loss_halted_date and self.daily_loss_halted_date != today:
                self.daily_loss_halted_date = None

    def _check_month_rollover(self, bar_dt: datetime) -> None:
        ym = bar_dt.strftime("%Y-%m")
        if self.last_month_anchor != ym:
            if self.last_month_anchor is not None:
                month_pnl = self._equity() - self.month_start_equity
                self.monthly_pnl_history.append(month_pnl)
                self.log.info(f"📅 月度结算 {self.last_month_anchor}: PnL={month_pnl:.2f}")
                self._execute_monthly_withdrawal(month_pnl)
            self.last_month_anchor = ym
            self.month_start_equity = self._equity()

    # =========================================================================
    # L3 熔断
    # =========================================================================
    def _is_open_blocked(self) -> bool:
        if self.daily_loss_halted_date == self.daily_anchor_date:
            return True
        if self.bar_counter_15m < self.pause_open_until_bar:
            return True
        if self._drawdown_pct() >= self.cfg.drawdown_full_halt_pct:
            return True
        return False

    def _check_daily_loss_halt(self) -> None:
        if self.daily_loss_halted_date == self.daily_anchor_date:
            return
        if self._daily_pnl_pct() <= -self.cfg.daily_loss_halt_pct:
            self.daily_loss_halted_date = self.daily_anchor_date
            self.log.warning(f"🛑 [L3-a] 单日亏损 {self._daily_pnl_pct()*100:.2f}%")

    def _apply_drawdown_tier(self) -> None:
        dd = self._drawdown_pct()
        if dd >= self.cfg.drawdown_full_halt_pct:
            self.effective_margin_cap_pct = 0.0
        elif dd >= self.cfg.drawdown_lower_risk_pct:
            self.effective_margin_cap_pct = self.cfg.max_margin_usage_pct * 0.25
        elif dd >= self.cfg.drawdown_halve_pct:
            self.effective_margin_cap_pct = self.cfg.max_margin_usage_pct * 0.5
        else:
            self.effective_margin_cap_pct = self.cfg.max_margin_usage_pct

    # =========================================================================
    # L2 隔夜
    # =========================================================================
    def _enforce_overnight_cap(self) -> None:
        equity = self._equity()
        used = self._used_margin()
        cap = equity * self.cfg.overnight_max_margin_pct
        if used <= cap:
            return
        position = self._get_open_position()
        if position is None:
            return
        excess_ratio = (used - cap) / used
        raw_cut = float(position.quantity) * excess_ratio
        if raw_cut < 1.0:
            return
        cut_qty = self.instrument.make_qty(raw_cut)
        cut_qty = self.instrument.make_qty(float(position.quantity) * excess_ratio)
        if float(cut_qty) <= 0:
            return
        sell_side = (OrderSide.SELL if position.side == PositionSide.LONG
                     else OrderSide.BUY)
        self._submit_reduce(cut_qty, sell_side)
        self.log.warning(f"🌙 [L2 隔夜] 减仓 {excess_ratio*100:.1f}%")

    # =========================================================================
    # 动态杠杆
    # =========================================================================
    def _get_dynamic_leverage(self) -> float:
        if not (self.atr_short_15m.initialized and self.atr_long_15m.initialized):
            return self.cfg.base_leverage
        atr_now = self.atr_short_15m.value
        atr_mean = self.atr_long_15m.value
        if atr_now <= 0:
            return self.cfg.base_leverage
        vol_ratio = atr_mean / atr_now
        return max(
            self.cfg.min_leverage,
            min(self.cfg.base_leverage, self.cfg.base_leverage * vol_ratio),
        )

    # =========================================================================
    # 开仓 — 50% 保证金
    # =========================================================================
    def _try_open(self, price: float) -> None:
        self._apply_drawdown_tier()
        if self._is_open_blocked():
            return
        if self.trend_direction == 0:
            return

        equity = self._equity()
        if equity <= 0 or self.effective_margin_cap_pct <= 0:
            return

        leverage = self._get_dynamic_leverage()
        margin = equity * self.effective_margin_cap_pct
        notional = margin * leverage
        raw_qty = notional / price

        if raw_qty * price < self.cfg.min_notional:
            return
        qty = self.instrument.make_qty(raw_qty)
        if float(qty) <= 0:
            return

        if self.trend_direction == 1:
            side = OrderSide.BUY
            side_name = "LONG"
        else:
            side = OrderSide.SELL
            side_name = "SHORT"

        order = self.order_factory.market(
            instrument_id=self.instrument_id,
            order_side=side,
            quantity=qty,
        )
        self.submit_order(order)

        self.current_side = side_name
        self.tp_step = 0
        self.risk_locked = False
        self.cvd_since_low = 0.0

        self.log.info(
            f"{'🟢' if side_name == 'LONG' else '🔴'} {side_name} | "
            f"qty={float(qty):.4f} @ {price:.4f} | lev={leverage:.2f}x | "
            f"margin={margin:.2f}"
        )

    # =========================================================================
    # 止盈
    # =========================================================================
    def _check_take_profit(self, roi: float, position) -> bool:
        total_qty = float(position.quantity)
        close_side = (OrderSide.SELL if position.side == PositionSide.LONG
                      else OrderSide.BUY)

        if roi >= self.cfg.tp3_pct and self.tp_step < 3:
            self.close_position(position)
            self.tp_step = 3
            self.log.info(f"🎯 TP3 (+{roi*100:.1f}%) 全平")
            self._reset_position_state()
            return True
        if roi >= self.cfg.tp2_pct and self.tp_step < 2:
            cut = self.instrument.make_qty(total_qty * 0.3)
            self._submit_reduce(cut, close_side)
            self.tp_step = 2
            self.log.info(f"🎯 TP2 (+{roi*100:.1f}%) 减 30%")
            return True
        if roi >= self.cfg.tp1_pct and self.tp_step < 1:
            cut = self.instrument.make_qty(total_qty * 0.3)
            self._submit_reduce(cut, close_side)
            self.tp_step = 1
            self.log.info(f"🎯 TP1 (+{roi*100:.1f}%) 减 30%")
            return True
        return False

    # =========================================================================
    # 止损
    # =========================================================================
    def _check_risk_control(self, roi: float, position) -> bool:
        if roi <= -self.cfg.sl_full_pct:
            self.log.warning(f"⚠️ SL (-{abs(roi)*100:.1f}%) 全平")
            self.close_position(position)
            self._reset_position_state()
            return True
        if roi <= -self.cfg.sl_halve_pct and not self.risk_locked:
            close_side = (OrderSide.SELL if position.side == PositionSide.LONG
                          else OrderSide.BUY)
            halve_qty = self.instrument.make_qty(float(position.quantity) * 0.5)
            self._submit_reduce(halve_qty, close_side)
            self.risk_locked = True
            self.log.warning(f"⚠️ SL (-{abs(roi)*100:.1f}%) 砍半")
            return True
        return False

    # =========================================================================
    # 下单辅助
    # =========================================================================
    def _submit_reduce(self, qty: Quantity, side: OrderSide) -> None:
        if float(qty) <= 0:
            return
        order = self.order_factory.market(
            instrument_id=self.instrument_id,
            order_side=side,
            quantity=qty,
            reduce_only=True,
        )
        self.submit_order(order)

    def _get_open_position(self):
        positions = self.cache.positions_open(instrument_id=self.instrument_id)
        for p in positions:
            if p.side in (PositionSide.LONG, PositionSide.SHORT):
                return p
        return None

    # =========================================================================
    # Position Events
    # =========================================================================
    def on_position_changed(self, event: PositionChanged) -> None:
        self._handle_pnl_event(event.realized_pnl, position_closed=False)

    def on_position_closed(self, event: PositionClosed) -> None:
        self._handle_pnl_event(event.realized_pnl, position_closed=True)

    def _handle_pnl_event(self, realized_pnl_obj, position_closed: bool) -> None:
        if realized_pnl_obj is None:
            return
        cur = float(realized_pnl_obj)
        delta = cur - self.last_realized_pnl
        self.last_realized_pnl = 0.0 if position_closed else cur

        if delta == 0:
            return

        if delta < 0:
            self.consecutive_losses += 1
            if self.consecutive_losses >= self.cfg.consecutive_losses_halt:
                self.pause_open_until_bar = self.bar_counter_15m + 1
                self.log.warning(f"🛑 [L3-b] 连续 {self.consecutive_losses} 笔亏损")
                self.consecutive_losses = 0
        else:
            self.consecutive_losses = 0

        equity = self._equity()
        if equity > self.equity_high_water:
            self.equity_high_water = equity

        self._check_daily_loss_halt()
        self._apply_drawdown_tier()

    # =========================================================================
    # 提款阶梯
    # =========================================================================
    def _evaluate_withdrawal_tier(self) -> None:
        equity = self._equity()
        if equity <= self.cfg.tier_demote_threshold:
            if self.current_withdraw_tier != 1:
                self.log.warning(f"⬇️  退回 Tier 1")
            self.current_withdraw_tier = 1
            return
        recent2 = self.monthly_pnl_history[-2:]
        if (equity > self.cfg.tier1_max
                and len(recent2) >= 2 and all(p > 0 for p in recent2)
                and self.current_withdraw_tier < 2):
            self.current_withdraw_tier = 2
        if (equity > self.cfg.tier2_max
                and self._drawdown_pct() < self.cfg.tier3_max_drawdown_pct
                and self.current_withdraw_tier < 3):
            self.current_withdraw_tier = 3

    def _execute_monthly_withdrawal(self, month_pnl: float) -> None:
        if month_pnl <= 0:
            return
        if self._drawdown_pct() > self.cfg.pause_withdraw_drawdown_pct:
            return
        ratio = {1: self.cfg.tier1_withdraw_ratio, 2: self.cfg.tier2_withdraw_ratio,
                 3: self.cfg.tier3_withdraw_ratio}.get(self.current_withdraw_tier, 0.0)
        if ratio <= 0:
            return
        amount = month_pnl * ratio
        self.cumulative_withdrawn += amount
        self.log.info(f"💸 [Tier {self.current_withdraw_tier}] 提款 {amount:.2f}")

    # =========================================================================
    # Reset
    # =========================================================================
    def _reset_position_state(self) -> None:
        self.tp_step = 0
        self.risk_locked = False
        self.current_side = None
        self.cvd_since_low = 0.0