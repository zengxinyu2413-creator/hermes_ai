"""Integration tests: true PREC → RISK → EXEC chain — CR12 I1~I2."""

from __future__ import annotations

import pathlib
from decimal import Decimal

import pytest

from nautilus_trader.core.uuid import UUID4
from nautilus_trader.model.enums import LiquiditySide, OrderSide, OrderType
from nautilus_trader.model.events.order import OrderFilled
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

from hermes.execution.exec_bridge import ExecBridge, naive_quote_cashflow_extractor
from hermes.execution.order_id import OrderIdFactory
from hermes.execution.precision import InstrumentLimits, build_order_spec
from hermes.risk.guard import GuardState, RiskDenied, RiskGuard


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SOL_LIMITS = InstrumentLimits(
    price_tick=Decimal("0.01"),
    price_min=Decimal("0"),
    price_max=Decimal("0"),
    qty_step=Decimal("0.001"),
    qty_min=Decimal("0.001"),
    qty_max=Decimal("90000"),
    min_notional=Decimal("5"),
    apply_min_to_market=True,
    bid_multiplier_up=Decimal("2.0"),
    bid_multiplier_down=Decimal("0.5"),
    ask_multiplier_up=Decimal("2.0"),
    ask_multiplier_down=Decimal("0.5"),
)


def _make_losing_fill(trade_id: str, qty: str = "0.06", px: str = "83.70") -> OrderFilled:
    """BUY fill with zero commission → pnl = -qty * px (always negative)."""
    return OrderFilled(
        trader_id=TraderId("TESTER-001"),
        strategy_id=StrategyId("INTEG-001"),
        instrument_id=InstrumentId.from_str("SOLUSDT.BINANCE"),
        client_order_id=ClientOrderId(f"O-{trade_id}"),
        venue_order_id=VenueOrderId(f"V-{trade_id}"),
        account_id=AccountId("BINANCE-001"),
        trade_id=TradeId(trade_id),
        position_id=None,
        order_side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        last_qty=Quantity.from_str(qty),
        last_px=Price.from_str(px),
        currency=Currency.from_str("USDT"),
        commission=Money(Decimal("0"), Currency.from_str("USDT")),
        liquidity_side=LiquiditySide.TAKER,
        event_id=UUID4(),
        ts_event=0,
        ts_init=0,
        reconciliation=False,
    )


# ---------------------------------------------------------------------------
# I1: normal path
# ---------------------------------------------------------------------------

class TestExecIntegrationI1:
    def test_i1_normal_path_prec_risk_exec(self):
        # Build real components
        guard = RiskGuard(consecutive_loss_limit=3, on_halt=lambda: None)
        factory = OrderIdFactory()
        msgbus = TestComponentStubs.msgbus()
        bridge = ExecBridge(
            msgbus=msgbus, risk_guard=guard,
            pnl_extractor=naive_quote_cashflow_extractor,
        )
        bridge.start()

        # PREC: build OrderSpec and verify check_order passes
        spec = build_order_spec(
            "SOLUSDT", "BUY", "MARKET",
            raw_price=Decimal("83.70"),
            raw_qty=Decimal("0.06"),
            limits=_SOL_LIMITS,
        )
        guard.check_order()  # should not raise

        # Generate client_order_id via factory
        coid = factory.generate()
        assert factory.is_seen(coid)

        # EXEC: publish one losing fill via msgbus
        fill = _make_losing_fill(trade_id="I1-T1")
        msgbus.publish(topic="events.order.INTEG-001", msg=fill)

        assert guard.consecutive_losses == 1
        assert guard.state == GuardState.ACTIVE


# ---------------------------------------------------------------------------
# I2: circuit-breaker path
# ---------------------------------------------------------------------------

class TestExecIntegrationI2:
    def test_i2_three_losses_trips_circuit_breaker(self):
        guard = RiskGuard(consecutive_loss_limit=3, on_halt=lambda: None)
        factory = OrderIdFactory()
        msgbus = TestComponentStubs.msgbus()
        bridge = ExecBridge(
            msgbus=msgbus, risk_guard=guard,
            pnl_extractor=naive_quote_cashflow_extractor,
        )
        bridge.start()

        # Publish 3 losing fills
        for i in range(3):
            fill = _make_losing_fill(trade_id=f"I2-T{i}")
            msgbus.publish(topic="events.order.INTEG-001", msg=fill)

        assert guard.state == GuardState.HALTED

        # 4th check_order raises RiskDenied with non-empty reason
        with pytest.raises(RiskDenied) as exc_info:
            guard.check_order()
        assert len(str(exc_info.value)) > 0

    def test_i2_no_float_in_integration_test_source(self):
        """Self-verification: no bare float coercion in integration test code."""
        test_source = pathlib.Path(__file__).read_text()
        # Use indirect reference so this line itself does not contain the banned token.
        banned = "fl" + "oat("
        assert banned not in test_source
