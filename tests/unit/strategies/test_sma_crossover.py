"""Unit tests for SMACrossoverStrategy signal logic.

Uses BacktestEngine as the in-memory test driver (no network I/O).
Each test constructs a known bar sequence that deterministically triggers
(or doesn't trigger) the target crossover event, then asserts on
BacktestResult.total_orders / total_positions.

Price sequence math for SMA(10)/SMA(30):
  - _flat_bars(30, "100.00")        → both SMAs=100, prev_fast_above_slow=False
  - + [bar("1000.00")]              → golden cross on that bar
  - + _flat_bars(10, "0.01")        → death cross on the 10th low bar
  - 20 bars at 100 + 10 bars at 300 → warmup ends with fast(300)>slow(166.67), prev=True (no signal)
  - + _flat_bars(10, "0.01")        → death cross at bar 35 (6th low bar), no prior position
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.backtest.results import BacktestResult
from nautilus_trader.config import LoggingConfig
from nautilus_trader.model.currencies import SOL, USDT
from nautilus_trader.model.data import Bar, BarSpecification, BarType
from nautilus_trader.model.enums import (
    AccountType,
    AggregationSource,
    BarAggregation,
    OmsType,
    PriceType,
)
from nautilus_trader.model.identifiers import InstrumentId, Symbol, TraderId, Venue
from nautilus_trader.model.instruments import CurrencyPair
from nautilus_trader.model.objects import Money, Price, Quantity

from hermes.adapters.nautilus.instruments import make_solusdt_binance
from hermes.strategies.sma_crossover import SMACrossoverConfig, SMACrossoverStrategy

_VENUE = Venue("BINANCE")
_INSTRUMENT_ID = InstrumentId(Symbol("SOLUSDT"), _VENUE)
_BAR_SPEC = BarSpecification(1, BarAggregation.MINUTE, PriceType.LAST)
_BAR_TYPE = BarType(_INSTRUMENT_ID, _BAR_SPEC, AggregationSource.EXTERNAL)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bar(price_str: str, ts: int) -> Bar:
    p = Price.from_str(price_str)
    return Bar(
        bar_type=_BAR_TYPE,
        open=p,
        high=p,
        low=p,
        close=p,
        volume=Quantity.from_str("1.00"),
        ts_event=ts * 60_000_000_000,
        ts_init=ts * 60_000_000_000,
    )


def _flat_bars(n: int, price: str, start_ts: int = 0) -> list[Bar]:
    return [_make_bar(price, start_ts + i) for i in range(n)]


def _run_backtest(bars: list[Bar]) -> BacktestResult:
    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id=TraderId("TEST-001"),
            logging=LoggingConfig(log_level="WARNING"),
        )
    )
    engine.add_venue(
        venue=_VENUE,
        oms_type=OmsType.NETTING,
        account_type=AccountType.CASH,
        starting_balances=[Money.from_str("100000.00 USDT")],
    )
    engine.add_instrument(make_solusdt_binance())
    engine.add_data(bars)
    config = SMACrossoverConfig(
        instrument_id=_INSTRUMENT_ID,
        bar_type=_BAR_TYPE,
        fast_period=10,
        slow_period=30,
        trade_size="1.00",
    )
    engine.add_strategy(SMACrossoverStrategy(config))
    engine.run()
    return engine.get_result()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSMACrossoverSignals:
    def test_warmup_no_signal(self) -> None:
        """29 bars (< slow_period=30): slow SMA never initialised → 0 orders."""
        result = _run_backtest(_flat_bars(29, "100.00"))
        assert result.total_orders == 0

    def test_golden_cross_triggers_buy(self) -> None:
        """30 flat bars then a spike: fast crosses above slow → exactly 1 BUY order."""
        bars = _flat_bars(30, "100.00") + [_make_bar("1000.00", 30)]
        result = _run_backtest(bars)
        assert result.total_orders == 1
        assert result.total_positions == 1

    def test_death_cross_closes_position(self) -> None:
        """Golden cross opens position; 10 low bars later the death cross closes it."""
        bars = (
            _flat_bars(30, "100.00")
            + [_make_bar("1000.00", 30)]
            + _flat_bars(10, "0.01", start_ts=31)
        )
        result = _run_backtest(bars)
        assert result.total_positions == 1  # one position existed
        assert result.total_orders == 2     # BUY + CLOSE from close_all_positions

    def test_no_reentry_while_holding(self) -> None:
        """After golden cross, elevated price keeps fast > slow.
        No death cross fires, so no second buy — total_orders stays at 1."""
        bars = (
            _flat_bars(30, "100.00")
            + [_make_bar("1000.00", 30)]
            + _flat_bars(20, "500.00", start_ts=31)
        )
        result = _run_backtest(bars)
        assert result.total_orders == 1

    def test_no_close_without_position(self) -> None:
        """Warmup ends with fast > slow (prev=True, no signal).
        Subsequent price drop triggers a death cross, but has_position=False
        so close_all_positions is never called — 0 orders total."""
        bars = (
            _flat_bars(20, "100.00")
            + _flat_bars(10, "300.00", start_ts=20)
            + _flat_bars(10, "0.01", start_ts=30)
        )
        result = _run_backtest(bars)
        assert result.total_orders == 0
