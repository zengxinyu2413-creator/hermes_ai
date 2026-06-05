"""One-shot LIMIT order strategy for testnet order submission (b3b-live, E2.5)."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.trading.config import StrategyConfig
from nautilus_trader.trading.strategy import Strategy


class OneShotConfig(StrategyConfig, frozen=True):
    """Config for a single one-shot LIMIT order."""

    instrument_id_str: str  # e.g. "ETHUSDT.BINANCE"
    order_side_str: str  # "BUY" or "SELL"
    price_str: str  # precision-rounded price as string
    quantity_str: str  # precision-rounded quantity as string


class OneShotStrategy(Strategy):  # type: ignore[misc]
    """Submit one LIMIT order; call on_done(venue_order_id, reason) on exchange response."""

    def __init__(
        self,
        config: OneShotConfig,
        on_done: Callable[[str | None, str | None], None],
    ) -> None:
        super().__init__(config)
        self._instrument_id = InstrumentId.from_str(config.instrument_id_str)
        self._order_side = (
            OrderSide.BUY if config.order_side_str.upper() == "BUY" else OrderSide.SELL
        )
        self._price = Price.from_str(config.price_str)
        self._quantity = Quantity.from_str(config.quantity_str)
        self._on_done = on_done
        self._submitted = False

    def on_stop(self) -> None:
        pass

    def on_start(self) -> None:
        order = self.order_factory.limit(
            instrument_id=self._instrument_id,
            order_side=self._order_side,
            quantity=self._quantity,
            price=self._price,
        )
        self.submit_order(order)
        self._submitted = True

    def on_order_accepted(self, event: Any) -> None:
        venue_order_id = str(event.venue_order_id)
        self._log.info(
            f"ORDER ACCEPTED  venue_order_id={venue_order_id}"
            f"  price={self._price}  qty={self._quantity}"
        )
        self._on_done(venue_order_id, None)
        self.shutdown_system(reason="oneshot order accepted")

    def on_order_rejected(self, event: Any) -> None:
        reason = str(event.reason)
        self._log.error(f"ORDER REJECTED  reason={reason}")
        self._on_done(None, reason)
        self.shutdown_system(reason="oneshot order rejected")
