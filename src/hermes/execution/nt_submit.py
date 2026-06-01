"""PREC translation layer (b): OrderSpec → NT SubmitOrder command.

Implements the b-seam: converts a validated hermes OrderSpec (Decimal) into a
NautilusTrader SubmitOrder command using real NT order types.

All qty/price back-conversions use Quantity.from_str(str(...)) / Price.from_str(str(...))
to avoid IEEE-754 representation drift (PREC-b recon Q3: the NT float-path helpers
use float internally and are forbidden in this layer).

Creating a SubmitOrder is not the same as sending it to a venue. SubmitOrder is
a command object; actual submission is done by strategy.submit_order(order) or
exec_client.submit_order. This layer does not connect to testnet.

Known gap (LC-PREC-b-1): Routing of the SubmitOrder command to the execution
engine (strategy / exec_client wiring) is out of scope for this layer.
"""

from __future__ import annotations

from nautilus_trader.core.uuid import UUID4
from nautilus_trader.execution.messages import SubmitOrder
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.objects import Price, Quantity

from hermes.execution.precision import OrderSpec

_SIDE_MAP: dict[str, OrderSide] = {
    "BUY": OrderSide.BUY,
    "SELL": OrderSide.SELL,
}


def order_spec_to_submit(
    order_spec: OrderSpec,
    instrument_id,
    factory,
    trader_id,
    strategy_id,
    clock,
) -> SubmitOrder:
    """Convert an OrderSpec to a NT SubmitOrder command object.

    qty/price back-conversion: Quantity.from_str(str(...)) / Price.from_str(str(...)).
    The NT float-path helpers are forbidden here (PREC-b recon Q3).

    MARKET: factory.market(instrument_id, side, qty) — price=0 on OrderSpec is NOT
        passed to the factory; market orders carry no price in NT.
    LIMIT:  factory.limit(instrument_id, side, qty, Price) — Price required.
    Other order_type → raises ValueError (no silent fallback).

    Parameters
    ----------
    order_spec : OrderSpec
        Validated order from hermes.execution.precision.build_order_spec.
    instrument_id : InstrumentId
        NT InstrumentId, e.g. InstrumentId.from_str("SOLUSDT.BINANCE").
    factory : OrderFactory
        Pre-initialised OrderFactory(trader_id, strategy_id, clock).
    trader_id : TraderId
    strategy_id : StrategyId
    clock : Clock
        Any NT Clock; ts_init = clock.timestamp_ns().

    Returns
    -------
    SubmitOrder
        Command object ready for routing; not yet sent to venue.

    Raises
    ------
    ValueError
        If order_spec.side is not 'BUY' or 'SELL'.
    ValueError
        If order_spec.order_type is not 'MARKET' or 'LIMIT'.
    """
    side_str = order_spec.side
    if side_str not in _SIDE_MAP:
        raise ValueError(f"Unknown order side: {side_str!r}; expected 'BUY' or 'SELL'")
    order_side = _SIDE_MAP[side_str]

    qty = Quantity.from_str(str(order_spec.quantity))

    order_type = order_spec.order_type
    if order_type == "MARKET":
        order = factory.market(instrument_id, order_side, qty)
    elif order_type == "LIMIT":
        price = Price.from_str(str(order_spec.price))
        order = factory.limit(instrument_id, order_side, qty, price)
    else:
        raise ValueError(f"Unknown order_type: {order_type!r}; expected 'MARKET' or 'LIMIT'")

    return SubmitOrder(
        trader_id=trader_id,
        strategy_id=strategy_id,
        order=order,
        command_id=UUID4(),
        ts_init=clock.timestamp_ns(),
    )
