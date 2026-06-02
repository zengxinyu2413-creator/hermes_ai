"""Inverse translation: NT Order → BinanceRestClient.new_order kwargs.

Converts a NautilusTrader Order (MarketOrder or LimitOrder) to a kwargs dict
ready for ``BinanceRestClient.new_order(**kwargs)``.

Inverse direction of order_spec_to_submit (nt_submit.py):
  nt_submit:    OrderSpec     → NT SubmitOrder command
  this module:  NT Order      → new_order kwargs dict
"""
# DORMANT (E2.5-b3b 起): 自建 exec 链 a/b1/b3a. live path 走 NT BinanceLiveExecClientFactory, 本链未被 cli.py 引用. 去留待 b3b-live testnet 验稳后重议, 见 handoff 6.3.
from __future__ import annotations

from decimal import Decimal
from typing import Any

_SUPPORTED_SIDES = {"BUY", "SELL"}
_SUPPORTED_ORDER_TYPES = {"MARKET", "LIMIT"}
_SUPPORTED_TIF = {"GTC", "IOC", "FOK"}


def nt_order_to_new_order_kwargs(order: Any) -> dict[str, Any]:
    """Convert a NT Order to BinanceRestClient.new_order kwargs.

    MARKET: returned dict has no 'price' or 'time_in_force' keys.
    LIMIT:  returned dict includes 'price' (Decimal) and 'time_in_force' (str).

    All Decimal conversions use Decimal(str(nt_obj)) — no float path.

    Raises
    ------
    ValueError
        If order.side is not BUY or SELL (e.g. NO_ORDER_SIDE).
    ValueError
        If order.order_type is not MARKET or LIMIT.
    ValueError
        If a LIMIT order has time_in_force not in {GTC, IOC, FOK}.
    """
    side_name = order.side.name
    if side_name not in _SUPPORTED_SIDES:
        raise ValueError(f"Unsupported order side: {side_name!r}; expected 'BUY' or 'SELL'")

    order_type_name = order.order_type.name
    if order_type_name not in _SUPPORTED_ORDER_TYPES:
        raise ValueError(
            f"Unsupported order_type: {order_type_name!r}; expected 'MARKET' or 'LIMIT'"
        )

    kwargs: dict[str, Any] = {
        "symbol": order.instrument_id.symbol.value,
        "side": side_name,
        "order_type": order_type_name,
        "quantity": Decimal(str(order.quantity)),
    }

    if order_type_name == "LIMIT":
        tif_name = order.time_in_force.name
        if tif_name not in _SUPPORTED_TIF:
            raise ValueError(
                f"Unsupported time_in_force for LIMIT order: {tif_name!r}; "
                f"expected one of {sorted(_SUPPORTED_TIF)}"
            )
        kwargs["price"] = Decimal(str(order.price))
        kwargs["time_in_force"] = tif_name

    return kwargs
