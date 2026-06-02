"""Binance Spot REST-backed NautilusTrader LiveExecutionClient."""
from __future__ import annotations

import asyncio
from typing import Any

from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.common.config import NautilusConfig
from nautilus_trader.common.providers import InstrumentProvider
from nautilus_trader.core.rust.model import AccountType, OmsType
from nautilus_trader.execution.messages import SubmitOrder
from nautilus_trader.live.execution_client import LiveExecutionClient
from nautilus_trader.model.enums import LiquiditySide
from nautilus_trader.model.identifiers import ClientId, TradeId, Venue, VenueOrderId
from nautilus_trader.model.objects import Currency, Money, Price, Quantity

from hermes.core.exceptions import BinanceAPIError
from hermes.exchanges.binance_rest import BinanceRestClient
from hermes.execution.nt_order_translate import nt_order_to_new_order_kwargs


class BinanceLiveExecClient(LiveExecutionClient):
    """NT LiveExecutionClient backed by BinanceRestClient for Spot testnet orders.

    Implements the b3a minimum:
        _connect / _disconnect / _submit_order (submitted → accepted/rejected + fills).
    All other LiveExecutionClient stubs remain raising NotImplementedError.
    Full TradingNode wiring is deferred to b3b.
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        client_id: ClientId,
        venue: Venue | None,
        oms_type: OmsType,
        account_type: AccountType,
        base_currency: Currency | None,
        instrument_provider: InstrumentProvider,
        msgbus: MessageBus,
        cache: Cache,
        clock: LiveClock,
        rest_client: BinanceRestClient,
        config: NautilusConfig | None = None,
    ) -> None:
        super().__init__(
            loop=loop,
            client_id=client_id,
            venue=venue,
            oms_type=oms_type,
            account_type=account_type,
            base_currency=base_currency,
            instrument_provider=instrument_provider,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            config=config,
        )
        self._rest_client: BinanceRestClient = rest_client

    def _now_ns(self) -> int:
        return int(self._clock.timestamp_ns())

    async def _connect(self) -> None:
        await self._rest_client.connect()

    async def _disconnect(self) -> None:
        await self._rest_client.aclose()

    async def _submit_order(self, command: SubmitOrder) -> None:
        order = command.order
        ts_submit = self._now_ns()

        # Segment 1: NT required pre-submission event
        self.generate_order_submitted(
            order.strategy_id,
            order.instrument_id,
            order.client_order_id,
            ts_submit,
        )

        # Segment 2: translate + submit to Binance
        try:
            kwargs = nt_order_to_new_order_kwargs(order)
            resp: dict[str, Any] = await self._rest_client.new_order(**kwargs)
        except (ValueError, BinanceAPIError) as exc:
            self.generate_order_rejected(
                order.strategy_id,
                order.instrument_id,
                order.client_order_id,
                str(exc),
                self._now_ns(),
            )
            return

        # Segment 3: map Binance status → NT events
        status = str(resp.get("status", ""))
        venue_order_id = VenueOrderId(str(resp["orderId"]))
        transact_ns = int(resp.get("transactTime", ts_submit // 1_000_000)) * 1_000_000

        if status == "REJECTED":
            self.generate_order_rejected(
                order.strategy_id,
                order.instrument_id,
                order.client_order_id,
                str(resp.get("msg", "REJECTED")),
                transact_ns,
            )
            return

        self.generate_order_accepted(
            order.strategy_id,
            order.instrument_id,
            order.client_order_id,
            venue_order_id,
            transact_ns,
        )

        if status in ("FILLED", "PARTIALLY_FILLED"):
            for fill in resp.get("fills", []):
                quote_currency = Currency.from_str(fill["commissionAsset"])
                self.generate_order_filled(
                    order.strategy_id,
                    order.instrument_id,
                    order.client_order_id,
                    venue_order_id,
                    None,  # venue_position_id — Spot has no position
                    TradeId(str(fill["tradeId"])),
                    order.side,
                    order.order_type,
                    Quantity.from_str(fill["qty"]),
                    Price.from_str(fill["price"]),
                    quote_currency,
                    Money(float(fill["commission"]), quote_currency),
                    LiquiditySide.NO_LIQUIDITY_SIDE,  # b3a placeholder; calibrate from first live fill in b3b
                    transact_ns,
                )
