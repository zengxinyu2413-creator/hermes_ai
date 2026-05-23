"""Stateless adapter: hermes Binance types → nautilus-trader data objects.

Converts ``Kline`` → ``Bar`` and ``Trade`` → ``TradeTick`` for use with
nautilus-trader's backtesting and execution engines.

This adapter is a pure transformation. It does not validate semantic
correctness of input data (e.g. negative prices, NaN). Validation is the
responsibility of the upstream producer.
"""
from __future__ import annotations

from decimal import Decimal

from nautilus_trader.model.data import Bar, BarSpecification, BarType, TradeTick
from nautilus_trader.model.enums import (
    AggregationSource,
    AggressorSide,
    BarAggregation,
    PriceType,
)
from nautilus_trader.model.identifiers import InstrumentId, Symbol, TradeId, Venue
from nautilus_trader.model.objects import Price, Quantity

from hermes.exchanges.binance_contracts import KlineInterval
from hermes.exchanges.binance_contracts import Kline
from hermes.exchanges.binance_contracts import Trade

_BINANCE_VENUE = Venue("BINANCE")

# Maps hermes KlineInterval to (step, BarAggregation) for nautilus BarSpecification.
# TODO: SEC_1/WEEK_1/MONTH_1 supported by nautilus but not enabled here yet
_INTERVAL_TO_BARSPEC: dict[KlineInterval, tuple[int, BarAggregation]] = {
    KlineInterval.MIN_1: (1, BarAggregation.MINUTE),
    KlineInterval.MIN_5: (5, BarAggregation.MINUTE),
    KlineInterval.MIN_15: (15, BarAggregation.MINUTE),
    KlineInterval.MIN_30: (30, BarAggregation.MINUTE),
    KlineInterval.HOUR_1: (1, BarAggregation.HOUR),
    KlineInterval.HOUR_4: (4, BarAggregation.HOUR),
    KlineInterval.DAY_1: (1, BarAggregation.DAY),
}


def build_instrument_id(symbol: str) -> InstrumentId:
    """Build a nautilus InstrumentId for a Binance symbol.

    Example: build_instrument_id("SOLUSDT") -> InstrumentId("SOLUSDT.BINANCE")

    Symbol is upper-cased to match Binance convention.
    """
    return InstrumentId(Symbol(symbol.upper()), _BINANCE_VENUE)


def build_bar_type(symbol: str, interval: KlineInterval) -> BarType:
    """Build a nautilus BarType for a Binance kline stream.

    Maps hermes KlineInterval to nautilus BarSpecification (step, aggregation).
    Example: build_bar_type("SOLUSDT", KlineInterval.MIN_1)
             -> BarType with spec 1-MINUTE-LAST-EXTERNAL

    Raises:
        NotImplementedError: if interval has no direct nautilus BarAggregation
                             mapping (e.g. SEC_1, WEEK_1, MONTH_1, MIN_3, DAY_3).
    """
    if interval not in _INTERVAL_TO_BARSPEC:
        raise NotImplementedError(
            f"KlineInterval {interval!r} has no direct nautilus BarAggregation mapping; "
            "add it to _INTERVAL_TO_BARSPEC to enable support."
        )
    step, aggregation = _INTERVAL_TO_BARSPEC[interval]
    instrument_id = build_instrument_id(symbol)
    spec = BarSpecification(step, aggregation, PriceType.LAST)
    return BarType(instrument_id, spec, AggregationSource.EXTERNAL)


def kline_to_bar(
    kline: Kline,
    *,
    bar_type: BarType,
    price_precision: int,
    size_precision: int,
) -> Bar:
    """Convert a hermes Kline to a nautilus Bar.

    Args:
        kline: hermes Kline. MUST have is_closed=True; raises if False.
        bar_type: nautilus BarType identifying the instrument and timeframe.
                  Caller is responsible for building this consistently with
                  kline.symbol and kline.interval via build_bar_type().
        price_precision: decimal places for nautilus Price (e.g. 2 for BTCUSDT, 4 for SOLUSDT).
        size_precision: decimal places for nautilus Quantity (volume).

    Returns:
        nautilus Bar with ts_event = kline.open_time_ms * 1_000_000 (ms→ns),
        ts_init = kline.close_time_ms * 1_000_000.

    Raises:
        ValueError: if kline.is_closed is False (cannot convert in-progress bars).

    Note:
        If a Decimal value has more decimal places than ``price_precision`` /
        ``size_precision``, it will be rounded using Python's default (banker's
        rounding, ROUND_HALF_EVEN). Caller is expected to pass precision values
        that match the instrument's tick size.
    """
    if not kline.is_closed:
        raise ValueError(
            f"Cannot convert in-progress kline to Bar (kline.is_closed is False): "
            f"symbol={kline.symbol!r} interval={kline.interval!r}"
        )

    def _price(d: Decimal) -> Price:
        return Price.from_str(format(d, f".{price_precision}f"))

    def _qty(d: Decimal) -> Quantity:
        return Quantity.from_str(format(d, f".{size_precision}f"))

    return Bar(
        bar_type=bar_type,
        open=_price(kline.open),
        high=_price(kline.high),
        low=_price(kline.low),
        close=_price(kline.close),
        volume=_qty(kline.volume),
        ts_event=kline.open_time_ms * 1_000_000,
        ts_init=kline.close_time_ms * 1_000_000,
    )


def trade_to_tick(
    trade: Trade,
    *,
    instrument_id: InstrumentId,
    price_precision: int,
    size_precision: int,
) -> TradeTick:
    """Convert a hermes Trade to a nautilus TradeTick.

    AggressorSide mapping:
        - trade.is_buyer_maker=True  -> AggressorSide.SELLER (the taker SOLD)
        - trade.is_buyer_maker=False -> AggressorSide.BUYER  (the taker BOUGHT)

    Args:
        trade: hermes Trade.
        instrument_id: nautilus InstrumentId (caller builds via build_instrument_id()).
        price_precision: decimal places for Price.
        size_precision: decimal places for Quantity.

    Returns:
        nautilus TradeTick with ts_event = trade.time_ms * 1_000_000,
        ts_init = ts_event.

    Note:
        If a Decimal value has more decimal places than ``price_precision`` /
        ``size_precision``, it will be rounded using Python's default (banker's
        rounding, ROUND_HALF_EVEN). Caller is expected to pass precision values
        that match the instrument's tick size.
    """
    aggressor_side = AggressorSide.SELLER if trade.is_buyer_maker else AggressorSide.BUYER
    ts = trade.time_ms * 1_000_000
    return TradeTick(
        instrument_id=instrument_id,
        price=Price.from_str(format(trade.price, f".{price_precision}f")),
        size=Quantity.from_str(format(trade.qty, f".{size_precision}f")),
        aggressor_side=aggressor_side,
        trade_id=TradeId(str(trade.trade_id)),
        ts_event=ts,
        ts_init=ts,
    )
