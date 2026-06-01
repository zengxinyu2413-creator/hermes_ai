"""ExecBridge: NT order-event bus → RiskGuard adapter with fill deduplication."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Callable, Optional

from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.events.order import OrderCanceled, OrderFilled, OrderRejected
from nautilus_trader.model.events.position import PositionChanged, PositionClosed, PositionOpened

from hermes.core.exceptions import ConfigurationError
from hermes.execution.events import PostOnlyRejected


def null_extractor(event) -> Optional[Decimal]:
    """Default safe extractor: never feeds RiskGuard."""
    return None


def naive_quote_cashflow_extractor(event) -> Decimal:
    """
    Cash flow per fill in quote currency, Decimal end-to-end.

    Convention: SELL = positive (received quote), BUY = negative (paid quote).
    Commission subtracted (always cost).

    Suitable only for scalping/grid strategies where every fill counts as a P&L event.
    For trend-following strategies, use null_extractor (default) and wait for
    PositionEvent-based extractor in EXEC Wave 2.

    Out of scope: cumulative realized PnL (use PositionEvent in EXEC Wave 2).
    """
    side_sign = Decimal(1) if event.order_side == OrderSide.SELL else Decimal(-1)
    qty: Decimal = event.last_qty.as_decimal()
    px: Decimal = event.last_px.as_decimal()
    com: Decimal = event.commission.as_decimal()
    return side_sign * qty * px - com


def position_realized_pnl_extractor(event) -> Decimal:
    """
    Extract cumulative realized PnL from a PositionEvent via Money.as_decimal().

    CE3 semantics: returns NT's cumulative absolute realized_pnl directly.
    No delta calculation — the caller receives exactly what NT accumulated.
    Suitable for PositionOpened, PositionChanged, PositionClosed.

    Out of scope: delta-from-last-event tracking, cross-currency conversion,
    unrealized PnL (use event.unrealized_pnl for that).
    """
    return event.realized_pnl.as_decimal()


def _is_post_only_rejection(due_post_only: bool | None, reason: str) -> bool:
    if due_post_only is True:
        return True
    if due_post_only is False:
        return False
    low = reason.lower()
    return any(s in low for s in ("would immediately match", "post only", "post-only", "post_only"))


class ExecBridge:
    """
    Bridges NT order-event and position-event buses to RiskGuard with fill
    deduplication and configurable P&L extraction.

    In scope: subscribing to NT msgbus order events, OrderFilled deduplication
    by (client_order_id, trade_id), reconciliation guard, cross-currency
    commission guard, routing P&L to RiskGuard, log-only path for
    OrderRejected and OrderCanceled, PositionEvent subscription with
    configurable position extractor.

    Out of scope: persistence across process restart,
    cross-currency commission conversion,
    due_post_only routing to strategy layer (LC-EXEC-2),
    OrderPendingUpdate / OrderPendingCancel / OrderModifyRejected /
    OrderCancelRejected / OrderExpired / OrderTriggered handling.
    """

    def __init__(
        self,
        msgbus,
        risk_guard,
        pnl_extractor: Optional[Callable] = None,
        position_extractor: Optional[Callable] = None,
        logger=None,
    ) -> None:
        if pnl_extractor is not None and position_extractor is not None:
            raise ConfigurationError(
                "ExecBridge: pnl_extractor and position_extractor are mutually exclusive; "
                "at most one may be non-null to prevent double-feeding RiskGuard (LC-EXEC-4)"
            )
        self._msgbus = msgbus
        self._risk_guard = risk_guard
        self._pnl_extractor = pnl_extractor if pnl_extractor is not None else null_extractor
        self._position_extractor = position_extractor if position_extractor is not None else null_extractor
        self._log = logger if logger is not None else logging.getLogger(__name__)
        self._seen_fills: set = set()

    def start(self) -> None:
        """Subscribe to NT order and position event buses (wildcard, priority=10)."""
        self._msgbus.subscribe(topic="events.order.*", handler=self._handle_event, priority=10)
        self._msgbus.subscribe(topic="events.position.*", handler=self._handle_position_event, priority=10)

    def _handle_event(self, event) -> None:
        if isinstance(event, OrderFilled):
            self.on_order_filled(event)
        elif isinstance(event, OrderRejected):
            self.on_order_rejected(event)
        elif isinstance(event, OrderCanceled):
            self.on_order_canceled(event)
        # All other OrderEvent subtypes are intentionally not handled here.

    def _handle_position_event(self, event) -> None:
        if isinstance(event, (PositionOpened, PositionChanged, PositionClosed)):
            pnl = self._position_extractor(event)
            if pnl is not None:
                self._risk_guard.on_trade_result(pnl)

    def on_order_filled(self, event: OrderFilled) -> None:
        # Step 1: reconciliation guard — skip fills generated during reconciliation.
        if event.reconciliation:
            return

        # Step 2: idempotency guard — deduplicate by (client_order_id, trade_id).
        dedup_key = (event.client_order_id.value, event.trade_id.value)
        if dedup_key in self._seen_fills:
            return
        self._seen_fills.add(dedup_key)

        # Step 3: cross-currency commission guard.
        # LC-EXEC-3: commission denominated in a currency other than the fill's
        # quote currency is not supported; skip extractor to avoid incorrect P&L.
        if event.commission.currency.code != event.currency.code:
            return

        # Step 4: extract P&L signal.
        pnl = self._pnl_extractor(event)

        # Step 5: feed RiskGuard.
        if pnl is not None:
            self._risk_guard.on_trade_result(pnl)

    def on_order_rejected(self, event: OrderRejected) -> None:
        if _is_post_only_rejection(event.due_post_only, event.reason):
            self._msgbus.publish(
                "exec.post_only_rejected",
                PostOnlyRejected(
                    client_order_id=event.client_order_id.value,
                    reason=event.reason,
                    ts_event=event.ts_event,
                ),
            )
        self._log.info(
            "OrderRejected: client_order_id=%s reason=%r",
            event.client_order_id,
            event.reason,
        )

    def on_order_canceled(self, event: OrderCanceled) -> None:
        self._log.info("OrderCanceled: client_order_id=%s", event.client_order_id)
