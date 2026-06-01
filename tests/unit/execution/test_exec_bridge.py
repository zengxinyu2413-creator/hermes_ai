"""Tests for ExecBridge — CR12 T1~T11."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from nautilus_trader.core.uuid import UUID4
from nautilus_trader.model.enums import LiquiditySide, OrderSide, OrderType
from nautilus_trader.model.events.order import OrderCanceled, OrderFilled, OrderRejected
from nautilus_trader.model.identifiers import (
    AccountId,
    ClientOrderId,
    InstrumentId,
    StrategyId,
    TradeId,
    TraderId,
    VenueOrderId,
)
from nautilus_trader.model.objects import Currency, Money, Price, Quantity
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from hermes.core.exceptions import ConfigurationError
from hermes.execution.exec_bridge import ExecBridge, naive_quote_cashflow_extractor, null_extractor, position_realized_pnl_extractor
from hermes.risk.guard import GuardState, RiskGuard


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_guard(limit: int = 3) -> RiskGuard:
    return RiskGuard(consecutive_loss_limit=limit, on_halt=lambda: None)


def _make_order_filled(
    side: OrderSide = OrderSide.BUY,
    last_qty: str = "1.0",
    last_px: str = "100.0",
    commission: str = "0.0",
    commission_currency: str = "USDT",
    currency: str = "USDT",
    reconciliation: bool = False,
    client_order_id: str = "O-12345",
    trade_id: str = "T1",
) -> OrderFilled:
    return OrderFilled(
        trader_id=TraderId("TESTER-001"),
        strategy_id=StrategyId("TEST-001"),
        instrument_id=InstrumentId.from_str("SOLUSDT.BINANCE"),
        client_order_id=ClientOrderId(client_order_id),
        venue_order_id=VenueOrderId("V-12345"),
        account_id=AccountId("BINANCE-001"),
        trade_id=TradeId(trade_id),
        position_id=None,
        order_side=side,
        order_type=OrderType.MARKET,
        last_qty=Quantity.from_str(last_qty),
        last_px=Price.from_str(last_px),
        currency=Currency.from_str(currency),
        commission=Money(Decimal(commission), Currency.from_str(commission_currency)),
        liquidity_side=LiquiditySide.TAKER,
        event_id=UUID4(),
        ts_event=0,
        ts_init=0,
        reconciliation=reconciliation,
    )


def _make_order_rejected(client_order_id: str = "O-12345") -> OrderRejected:
    return OrderRejected(
        trader_id=TraderId("TESTER-001"),
        strategy_id=StrategyId("TEST-001"),
        instrument_id=InstrumentId.from_str("SOLUSDT.BINANCE"),
        client_order_id=ClientOrderId(client_order_id),
        account_id=AccountId("BINANCE-001"),
        reason="INSUFFICIENT_BALANCE",
        event_id=UUID4(),
        ts_event=0,
        ts_init=0,
    )


def _make_order_canceled(client_order_id: str = "O-12345") -> OrderCanceled:
    return OrderCanceled(
        trader_id=TraderId("TESTER-001"),
        strategy_id=StrategyId("TEST-001"),
        instrument_id=InstrumentId.from_str("SOLUSDT.BINANCE"),
        client_order_id=ClientOrderId(client_order_id),
        venue_order_id=VenueOrderId("V-12345"),
        account_id=AccountId("BINANCE-001"),
        event_id=UUID4(),
        ts_event=0,
        ts_init=0,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestExecBridgeT1:
    def test_t1_null_extractor_does_not_call_on_trade_result(self):
        real_guard = _make_guard()
        spy = MagicMock(wraps=real_guard)
        bridge = ExecBridge(msgbus=MagicMock(), risk_guard=spy)  # default null_extractor
        fill = _make_order_filled(side=OrderSide.BUY)
        bridge.on_order_filled(fill)
        spy.on_trade_result.assert_not_called()


class TestExecBridgeT2:
    def test_t2_naive_sell_fill_pnl_positive(self):
        real_guard = _make_guard()
        spy = MagicMock(wraps=real_guard)
        bridge = ExecBridge(
            msgbus=MagicMock(), risk_guard=spy,
            pnl_extractor=naive_quote_cashflow_extractor,
        )
        fill = _make_order_filled(side=OrderSide.SELL, last_qty="1.0", last_px="100.0",
                                   commission="0.0")
        bridge.on_order_filled(fill)
        spy.on_trade_result.assert_called_once()
        pnl = spy.on_trade_result.call_args[0][0]
        assert isinstance(pnl, Decimal)
        assert pnl > Decimal(0)


class TestExecBridgeT3:
    def test_t3_naive_buy_fill_pnl_negative(self):
        real_guard = _make_guard()
        spy = MagicMock(wraps=real_guard)
        bridge = ExecBridge(
            msgbus=MagicMock(), risk_guard=spy,
            pnl_extractor=naive_quote_cashflow_extractor,
        )
        fill = _make_order_filled(side=OrderSide.BUY, last_qty="1.0", last_px="100.0",
                                   commission="0.0")
        bridge.on_order_filled(fill)
        spy.on_trade_result.assert_called_once()
        pnl = spy.on_trade_result.call_args[0][0]
        assert isinstance(pnl, Decimal)
        assert pnl < Decimal(0)


class TestExecBridgeT4:
    def test_t4_order_rejected_no_risk_guard_no_extractor(self):
        spy_guard = MagicMock(spec=RiskGuard)
        spy_extractor = MagicMock(return_value=Decimal("50"))
        bridge = ExecBridge(msgbus=MagicMock(), risk_guard=spy_guard,
                            pnl_extractor=spy_extractor)
        bridge.on_order_rejected(_make_order_rejected())
        spy_guard.on_trade_result.assert_not_called()
        spy_extractor.assert_not_called()


class TestExecBridgeT5:
    def test_t5_order_canceled_no_risk_guard_no_extractor(self):
        spy_guard = MagicMock(spec=RiskGuard)
        spy_extractor = MagicMock(return_value=Decimal("50"))
        bridge = ExecBridge(msgbus=MagicMock(), risk_guard=spy_guard,
                            pnl_extractor=spy_extractor)
        bridge.on_order_canceled(_make_order_canceled())
        spy_guard.on_trade_result.assert_not_called()
        spy_extractor.assert_not_called()


class TestExecBridgeT6:
    def test_t6_reconciliation_fill_skips_extractor_and_risk_guard(self):
        spy_guard = MagicMock(spec=RiskGuard)
        spy_extractor = MagicMock(return_value=Decimal("50"))
        bridge = ExecBridge(msgbus=MagicMock(), risk_guard=spy_guard,
                            pnl_extractor=spy_extractor)
        fill = _make_order_filled(reconciliation=True)
        bridge.on_order_filled(fill)
        spy_extractor.assert_not_called()
        spy_guard.on_trade_result.assert_not_called()


class TestExecBridgeT7:
    def test_t7_cross_currency_commission_skips_extractor_and_risk_guard(self):
        # commission in SOL (base), fill priced in USDT (quote) → cross-currency
        spy_guard = MagicMock(spec=RiskGuard)
        spy_extractor = MagicMock(return_value=Decimal("50"))
        bridge = ExecBridge(msgbus=MagicMock(), risk_guard=spy_guard,
                            pnl_extractor=spy_extractor)
        fill = _make_order_filled(currency="USDT", commission_currency="SOL")
        bridge.on_order_filled(fill)
        spy_extractor.assert_not_called()
        spy_guard.on_trade_result.assert_not_called()


class TestExecBridgeT8:
    def test_t8_duplicate_fill_same_coid_and_trade_id_counted_once(self):
        real_guard = _make_guard()
        spy = MagicMock(wraps=real_guard)
        bridge = ExecBridge(msgbus=MagicMock(), risk_guard=spy,
                            pnl_extractor=naive_quote_cashflow_extractor)
        fill_a = _make_order_filled(client_order_id="O-DUP", trade_id="T1")
        fill_b = _make_order_filled(client_order_id="O-DUP", trade_id="T1")  # replay
        bridge.on_order_filled(fill_a)
        bridge.on_order_filled(fill_b)
        assert spy.on_trade_result.call_count == 1


class TestExecBridgeT9:
    def test_t9_different_trade_ids_same_coid_counted_separately(self):
        real_guard = _make_guard(limit=10)
        spy = MagicMock(wraps=real_guard)
        bridge = ExecBridge(msgbus=MagicMock(), risk_guard=spy,
                            pnl_extractor=naive_quote_cashflow_extractor)
        for i in range(3):
            fill = _make_order_filled(client_order_id="O-PARTIAL", trade_id=f"T-{i}")
            bridge.on_order_filled(fill)
        assert spy.on_trade_result.call_count == 3


class TestExecBridgeT10:
    def test_t10_real_msgbus_start_and_publish_triggers_handler(self):
        msgbus = TestComponentStubs.msgbus()
        real_guard = _make_guard(limit=10)
        bridge = ExecBridge(msgbus=msgbus, risk_guard=real_guard,
                            pnl_extractor=naive_quote_cashflow_extractor)
        bridge.start()

        fill = _make_order_filled(side=OrderSide.BUY, last_qty="1.0",
                                   last_px="100.0", commission="0.0",
                                   client_order_id="O-T10", trade_id="T10")
        # topic matches "events.order.*" wildcard
        msgbus.publish(topic="events.order.TEST-001", msg=fill)

        assert len(bridge._seen_fills) == 1
        assert real_guard.consecutive_losses == 1


class TestExecBridgeT11:
    def test_t11_unknown_order_event_returns_safely(self):
        bridge = ExecBridge(msgbus=MagicMock(), risk_guard=MagicMock())

        # Construct an OrderAccepted-like stub (not Filled/Rejected/Canceled)
        # Use OrderRejected as a proxy: it is an OrderEvent but not the three handled ones.
        # The simplest approach: pass an arbitrary object that is none of the three types.
        class _FakeEvent:
            pass

        bridge._handle_event(_FakeEvent())  # must not raise


# ── CE4: events.position.* subscription coexists with events.order.* ─────────

class TestCE4PositionSubscription:
    def test_start_subscribes_position_events(self):
        msgbus = MagicMock()
        bridge = ExecBridge(msgbus=msgbus, risk_guard=MagicMock())
        bridge.start()
        topics = [call.kwargs.get("topic") or call.args[0]
                  for call in msgbus.subscribe.call_args_list]
        assert "events.position.*" in topics

    def test_start_preserves_order_subscription(self):
        msgbus = MagicMock()
        bridge = ExecBridge(msgbus=msgbus, risk_guard=MagicMock())
        bridge.start()
        topics = [call.kwargs.get("topic") or call.args[0]
                  for call in msgbus.subscribe.call_args_list]
        assert "events.order.*" in topics

    def test_both_subscriptions_use_priority_10(self):
        msgbus = MagicMock()
        bridge = ExecBridge(msgbus=msgbus, risk_guard=MagicMock())
        bridge.start()
        for call in msgbus.subscribe.call_args_list:
            priority = call.kwargs.get("priority") or (call.args[2] if len(call.args) > 2 else None)
            assert priority == 10


# ── CE5: position path and order path deduplication are independent ───────────

class TestCE5NoDoubleFeed:
    def test_order_fill_and_position_change_no_double_feed(self):
        """Same fill event fires OrderFilled then PositionChanged.
        With null order extractor (default) + position extractor configured,
        RiskGuard is fed exactly once (from position path only).
        """
        from decimal import Decimal
        from unittest.mock import MagicMock, patch
        from nautilus_trader.model.events.position import PositionChanged
        from hermes.execution.exec_bridge import position_realized_pnl_extractor

        risk_guard = MagicMock()
        bridge = ExecBridge(
            msgbus=MagicMock(),
            risk_guard=risk_guard,
            # pnl_extractor left as null_extractor (default) — order path silent
            position_extractor=position_realized_pnl_extractor,
        )

        # Simulate OrderFilled (order path: null_extractor → no feed)
        fill = MagicMock()
        fill.reconciliation = False
        fill.client_order_id.value = "O-1"
        fill.trade_id.value = "T-1"
        fill.commission.currency.code = "USDT"
        fill.currency.code = "USDT"
        bridge.on_order_filled(fill)

        # Simulate PositionChanged (position path: position extractor → feed)
        pos_event = MagicMock(spec=PositionChanged)
        pos_event.realized_pnl.as_decimal.return_value = Decimal("5.00")
        bridge._handle_position_event(pos_event)

        # RiskGuard fed exactly once (position path), not twice
        risk_guard.on_trade_result.assert_called_once_with(Decimal("5.00"))


# ── CF1~CF5: Extractor mutual exclusion (LC-EXEC-4 structural fix) ────────────

class TestExtractorMutualExclusion:
    """CF2~CF5: both-non-null raises; exactly-one and both-null are allowed."""

    def test_cf2_both_non_null_raises_configuration_error(self):
        with pytest.raises(ConfigurationError) as exc_info:
            ExecBridge(
                msgbus=MagicMock(),
                risk_guard=MagicMock(),
                pnl_extractor=naive_quote_cashflow_extractor,
                position_extractor=position_realized_pnl_extractor,
            )
        assert isinstance(exc_info.value, ConfigurationError)

    def test_cf3a_only_pnl_extractor_constructs_successfully(self):
        bridge = ExecBridge(
            msgbus=MagicMock(),
            risk_guard=MagicMock(),
            pnl_extractor=naive_quote_cashflow_extractor,
        )
        assert bridge is not None

    def test_cf3b_only_position_extractor_constructs_successfully(self):
        bridge = ExecBridge(
            msgbus=MagicMock(),
            risk_guard=MagicMock(),
            position_extractor=position_realized_pnl_extractor,
        )
        assert bridge is not None

    def test_cf4_both_null_constructs_successfully(self):
        bridge = ExecBridge(msgbus=MagicMock(), risk_guard=MagicMock())
        assert bridge is not None

    def test_cf5_exception_message_identifies_mutual_exclusion(self):
        with pytest.raises(ConfigurationError) as exc_info:
            ExecBridge(
                msgbus=MagicMock(),
                risk_guard=MagicMock(),
                pnl_extractor=naive_quote_cashflow_extractor,
                position_extractor=position_realized_pnl_extractor,
            )
        msg = str(exc_info.value)
        assert "mutually exclusive" in msg
