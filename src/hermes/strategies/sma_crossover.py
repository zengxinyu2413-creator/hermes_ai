"""SMA crossover strategy for nautilus BacktestEngine."""
from __future__ import annotations

from nautilus_trader.indicators.averages import SimpleMovingAverage
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Quantity
from nautilus_trader.trading.strategy import Strategy, StrategyConfig


class SMACrossoverConfig(StrategyConfig, frozen=True):  # type: ignore[call-arg, misc]
    instrument_id: InstrumentId
    bar_type: BarType
    fast_period: int = 10
    slow_period: int = 30
    trade_size: str = "1.00"


class SMACrossoverStrategy(Strategy):  # type: ignore[misc]
    """SMA 交叉策略:快线上穿慢线买入,下穿平仓。仅做多。

    Assumption: on_bar is called only for *closed* bars (nautilus default).
    Signals are derived solely from bar.close — no look-ahead bias.
    """

    def __init__(self, config: SMACrossoverConfig) -> None:
        super().__init__(config)
        self._instrument_id: InstrumentId = config.instrument_id
        self._bar_type: BarType = config.bar_type
        self._trade_size: Quantity = Quantity.from_str(config.trade_size)

        self._fast_sma = SimpleMovingAverage(config.fast_period)
        self._slow_sma = SimpleMovingAverage(config.slow_period)

        # Track previous bar's relationship (True = fast > slow) for crossover detection
        self._prev_fast_above_slow: bool | None = None

    def on_start(self) -> None:
        self.subscribe_bars(self._bar_type)

    def on_bar(self, bar: Bar) -> None:
        # float 仅用于 SMA 指标内部比较,不流入任何下单 quantity/price 计算
        close_float = float(bar.close)
        self._fast_sma.update_raw(close_float)
        self._slow_sma.update_raw(close_float)

        if not (self._fast_sma.initialized and self._slow_sma.initialized):
            return

        fast_above_slow = self._fast_sma.value > self._slow_sma.value

        if self._prev_fast_above_slow is None:
            self._prev_fast_above_slow = fast_above_slow
            return

        crossed_up = not self._prev_fast_above_slow and fast_above_slow
        crossed_down = self._prev_fast_above_slow and not fast_above_slow
        self._prev_fast_above_slow = fast_above_slow

        has_position = self.portfolio.is_net_long(self._instrument_id)

        if crossed_up and not has_position:
            order = self.order_factory.market(
                instrument_id=self._instrument_id,
                order_side=OrderSide.BUY,
                quantity=self._trade_size,
            )
            self.submit_order(order)

        elif crossed_down and has_position:
            self.close_all_positions(self._instrument_id)

    def on_stop(self) -> None:
        pass
