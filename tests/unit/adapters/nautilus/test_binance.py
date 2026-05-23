"""Unit tests for hermes.adapters.nautilus.binance adapter functions."""
from decimal import Decimal

import pytest

from nautilus_trader.model.enums import AggressorSide, BarAggregation, AggregationSource, PriceType

from hermes.adapters.nautilus.binance import (
    build_bar_type,
    build_instrument_id,
    kline_to_bar,
    trade_to_tick,
)
from hermes.exchanges.binance_contracts import KlineInterval, Kline, Trade


# ---------------------------------------------------------------------------
# Helpers / shared fixtures
# ---------------------------------------------------------------------------

def _make_kline(
    *,
    symbol: str = "SOLUSDT",
    interval: KlineInterval = KlineInterval.MIN_1,
    open_time_ms: int = 1609459200000,
    close_time_ms: int = 1609459260000,
    open: str = "100.00",
    high: str = "101.50",
    low: str = "99.80",
    close: str = "101.00",
    volume: str = "1234.567",
    is_closed: bool = True,
) -> Kline:
    return Kline(
        symbol=symbol,
        interval=interval,
        open_time_ms=open_time_ms,
        close_time_ms=close_time_ms,
        open=Decimal(open),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal(volume),
        quote_volume=Decimal("124567.89"),
        trades=500,
        taker_buy_base_volume=Decimal("600.000"),
        taker_buy_quote_volume=Decimal("60600.00"),
        is_closed=is_closed,
    )


def _make_trade(
    *,
    symbol: str = "SOLUSDT",
    trade_id: int = 12345,
    price: str = "100.12",
    qty: str = "5.000",
    time_ms: int = 1609459200000,
    is_buyer_maker: bool = True,
) -> Trade:
    return Trade(
        symbol=symbol,
        trade_id=trade_id,
        price=Decimal(price),
        qty=Decimal(qty),
        time_ms=time_ms,
        is_buyer_maker=is_buyer_maker,
    )


# ---------------------------------------------------------------------------
# build_instrument_id
# ---------------------------------------------------------------------------

def test_build_instrument_id_lowercase_uppercased() -> None:
    result = build_instrument_id("solusdt")
    assert str(result) == "SOLUSDT.BINANCE"


def test_build_instrument_id_uppercase_preserved() -> None:
    result = build_instrument_id("BTCUSDT")
    assert str(result) == "BTCUSDT.BINANCE"


# ---------------------------------------------------------------------------
# build_bar_type
# ---------------------------------------------------------------------------

def test_build_bar_type_min_1() -> None:
    bt = build_bar_type("SOLUSDT", KlineInterval.MIN_1)
    assert bt.spec.step == 1
    assert bt.spec.aggregation == BarAggregation.MINUTE
    assert bt.spec.price_type == PriceType.LAST
    assert bt.aggregation_source == AggregationSource.EXTERNAL


def test_build_bar_type_min_5() -> None:
    bt = build_bar_type("SOLUSDT", KlineInterval.MIN_5)
    assert bt.spec.step == 5
    assert bt.spec.aggregation == BarAggregation.MINUTE


def test_build_bar_type_hour_1() -> None:
    bt = build_bar_type("BTCUSDT", KlineInterval.HOUR_1)
    assert bt.spec.step == 1
    assert bt.spec.aggregation == BarAggregation.HOUR


def test_build_bar_type_day_1() -> None:
    bt = build_bar_type("ETHUSDT", KlineInterval.DAY_1)
    assert bt.spec.step == 1
    assert bt.spec.aggregation == BarAggregation.DAY


def test_build_bar_type_unsupported_interval_raises() -> None:
    with pytest.raises(NotImplementedError, match="SEC_1"):
        build_bar_type("SOLUSDT", KlineInterval.SEC_1)


def test_build_bar_type_week_unsupported_raises() -> None:
    with pytest.raises(NotImplementedError, match="WEEK_1"):
        build_bar_type("SOLUSDT", KlineInterval.WEEK_1)


# ---------------------------------------------------------------------------
# kline_to_bar
# ---------------------------------------------------------------------------

def test_kline_to_bar_ohlcv_decimal_exact() -> None:
    kline = _make_kline(
        open="50000.00",
        high="50100.00",
        low="49900.55",
        close="50050.99",
        volume="1.500",
    )
    bt = build_bar_type("SOLUSDT", KlineInterval.MIN_1)
    bar = kline_to_bar(kline, bar_type=bt, price_precision=2, size_precision=3)

    assert str(bar.open) == "50000.00"
    assert str(bar.high) == "50100.00"
    assert str(bar.low) == "49900.55"
    assert str(bar.close) == "50050.99"
    assert str(bar.volume) == "1.500"


def test_kline_to_bar_ts_ms_to_ns_conversion() -> None:
    open_ms = 1609459200000
    close_ms = 1609459260000
    kline = _make_kline(open_time_ms=open_ms, close_time_ms=close_ms)
    bt = build_bar_type("SOLUSDT", KlineInterval.MIN_1)
    bar = kline_to_bar(kline, bar_type=bt, price_precision=2, size_precision=3)

    assert bar.ts_event == 1609459200000000000
    assert bar.ts_init == 1609459260000000000


def test_kline_to_bar_open_bar_raises() -> None:
    kline = _make_kline(is_closed=False)
    bt = build_bar_type("SOLUSDT", KlineInterval.MIN_1)
    with pytest.raises(ValueError, match="is_closed"):
        kline_to_bar(kline, bar_type=bt, price_precision=2, size_precision=3)


def test_kline_to_bar_price_precision_2_vs_4() -> None:
    kline = _make_kline(open="100.00", high="100.00", low="100.00", close="100.00")
    bt = build_bar_type("SOLUSDT", KlineInterval.MIN_1)

    bar2 = kline_to_bar(kline, bar_type=bt, price_precision=2, size_precision=3)
    bar4 = kline_to_bar(kline, bar_type=bt, price_precision=4, size_precision=3)

    assert str(bar2.open) == "100.00"
    assert str(bar4.open) == "100.0000"
    assert str(bar2.open) != str(bar4.open)


# ---------------------------------------------------------------------------
# trade_to_tick
# ---------------------------------------------------------------------------

def test_trade_to_tick_buyer_maker_true_gives_seller() -> None:
    trade = _make_trade(is_buyer_maker=True)
    instrument_id = build_instrument_id("SOLUSDT")
    tick = trade_to_tick(trade, instrument_id=instrument_id, price_precision=2, size_precision=3)
    assert tick.aggressor_side == AggressorSide.SELLER


def test_trade_to_tick_buyer_maker_false_gives_buyer() -> None:
    trade = _make_trade(is_buyer_maker=False)
    instrument_id = build_instrument_id("SOLUSDT")
    tick = trade_to_tick(trade, instrument_id=instrument_id, price_precision=2, size_precision=3)
    assert tick.aggressor_side == AggressorSide.BUYER


def test_trade_to_tick_price_qty_decimal_exact() -> None:
    trade = _make_trade(price="200.25", qty="3.750")
    instrument_id = build_instrument_id("SOLUSDT")
    tick = trade_to_tick(trade, instrument_id=instrument_id, price_precision=2, size_precision=3)

    assert str(tick.price) == "200.25"
    assert str(tick.size) == "3.750"


def test_trade_to_tick_ts_ms_to_ns_conversion() -> None:
    time_ms = 1609459200000
    trade = _make_trade(time_ms=time_ms)
    instrument_id = build_instrument_id("SOLUSDT")
    tick = trade_to_tick(trade, instrument_id=instrument_id, price_precision=2, size_precision=3)

    assert tick.ts_event == 1609459200000000000
    assert tick.ts_init == 1609459200000000000
    assert tick.ts_event == tick.ts_init
