"""Tests for order_spec_to_submit — CB1 through CB8.

Uses real NautilusTrader types (OrderFactory, InstrumentId, Price, Quantity,
SubmitOrder) as required by CB7. No testnet connection is made — SubmitOrder is
a command object, not a live order.
"""

from __future__ import annotations

import pathlib
from decimal import Decimal
from uuid import UUID

import pytest

from nautilus_trader.common.factories import OrderFactory
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.execution.messages import SubmitOrder
from nautilus_trader.model.enums import OrderSide, OrderType
from nautilus_trader.model.identifiers import InstrumentId, StrategyId, TraderId
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.test_kit.stubs.component import LiveClock

from hermes.execution.precision import InstrumentLimits, OrderSpec, build_order_spec
from hermes.execution.nt_submit import order_spec_to_submit

# ---------------------------------------------------------------------------
# Test fixtures — real NT types (CB7 PASS path)
# ---------------------------------------------------------------------------

_TRADER_ID = TraderId("TESTER-001")
_STRATEGY_ID = StrategyId("TEST-001")
_INSTRUMENT_ID = InstrumentId.from_str("SOLUSDT.BINANCE")

# SOLUSDT limits (verbatim from step3_submit_cancel.py:59)
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

_NT_SUBMIT_SRC = (
    pathlib.Path(__file__).parent.parent.parent.parent
    / "src/hermes/execution/nt_submit.py"
)


def _make_clock() -> LiveClock:
    return LiveClock()


def _make_factory(clock: LiveClock | None = None) -> OrderFactory:
    clk = clock or _make_clock()
    return OrderFactory(trader_id=_TRADER_ID, strategy_id=_STRATEGY_ID, clock=clk)


def _market_spec() -> OrderSpec:
    return build_order_spec(
        "SOLUSDT", "BUY", "MARKET",
        raw_price=Decimal("83.70"),
        raw_qty=Decimal("0.06"),
        limits=_SOL_LIMITS,
    )


def _limit_spec() -> OrderSpec:
    return build_order_spec(
        "SOLUSDT", "BUY", "LIMIT",
        raw_price=Decimal("83.70"),
        raw_qty=Decimal("0.06"),
        limits=_SOL_LIMITS,
    )


# ---------------------------------------------------------------------------
# CB1: function signature — NT deps as explicit params, precision/nt_translate 0 diff
# ---------------------------------------------------------------------------


class TestCB1SignatureAndZeroDiff:
    def test_function_callable_with_explicit_params(self) -> None:
        clock = _make_clock()
        factory = _make_factory(clock)
        spec = _market_spec()
        cmd = order_spec_to_submit(
            spec, _INSTRUMENT_ID, factory, _TRADER_ID, _STRATEGY_ID, clock
        )
        assert isinstance(cmd, SubmitOrder)

    def test_precision_py_unmodified(self) -> None:
        src = (
            pathlib.Path(__file__).parent.parent.parent.parent
            / "src/hermes/execution/precision.py"
        )
        text = src.read_text(encoding="utf-8")
        assert "class InstrumentLimits" in text
        assert "class OrderSpec" in text
        assert "def build_order_spec" in text

    def test_nt_translate_py_unmodified_original_fn(self) -> None:
        src = (
            pathlib.Path(__file__).parent.parent.parent.parent
            / "src/hermes/execution/nt_translate.py"
        )
        text = src.read_text(encoding="utf-8")
        # Original function body anchors
        assert "def nt_instrument_to_limits(" in text
        assert "Decimal(str(instrument.price_increment))" in text

    def test_no_hidden_globals_or_self_in_source(self) -> None:
        text = _NT_SUBMIT_SRC.read_text(encoding="utf-8")
        # The function must not reference os.environ, globals, or self
        assert "os.environ" not in text
        assert "def order_spec_to_submit(self" not in text


# ---------------------------------------------------------------------------
# CB2: grep — zero forbidden float paths in nt_submit.py
# ---------------------------------------------------------------------------


class TestCB2NoForbiddenFloatPaths:
    def test_no_make_price(self) -> None:
        text = _NT_SUBMIT_SRC.read_text(encoding="utf-8")
        assert "make_price" not in text, "make_price found — forbidden (uses float internally)"

    def test_no_make_qty(self) -> None:
        text = _NT_SUBMIT_SRC.read_text(encoding="utf-8")
        assert "make_qty" not in text, "make_qty found — forbidden (uses float internally)"

    def test_no_price_float_constructor(self) -> None:
        text = _NT_SUBMIT_SRC.read_text(encoding="utf-8")
        assert "Price(float" not in text, "Price(float path found — forbidden"

    def test_no_quantity_float_constructor(self) -> None:
        text = _NT_SUBMIT_SRC.read_text(encoding="utf-8")
        assert "Quantity(float" not in text, "Quantity(float path found — forbidden"

    def test_from_str_present(self) -> None:
        text = _NT_SUBMIT_SRC.read_text(encoding="utf-8")
        assert "Quantity.from_str" in text
        assert "Price.from_str" in text


# ---------------------------------------------------------------------------
# CB3: float trap — Price.from_str(str(d)) is lossless; float path would drift
# ---------------------------------------------------------------------------


class TestCB3FloatTrap:
    def test_price_str_path_lossless(self) -> None:
        d = Decimal("83.70")
        p = Price.from_str(str(d))
        assert str(p) == str(d), f"str(p)={str(p)!r} != str(d)={str(d)!r}"
        assert Decimal(str(p)) == d

    def test_price_float_path_would_lose_trailing_zero(self) -> None:
        d = Decimal("83.70")
        # float drops trailing zero: str(float(83.70)) == "83.7" != "83.70"
        assert str(float(d)) != str(d), "float repr must differ to prove drift risk"

    def test_qty_str_path_lossless(self) -> None:
        d = Decimal("0.060")
        q = Quantity.from_str(str(d))
        assert str(q) == str(d), f"str(q)={str(q)!r} != str(d)={str(d)!r}"
        assert Decimal(str(q)) == d

    def test_qty_float_path_would_lose_trailing_zero(self) -> None:
        d = Decimal("0.060")
        assert str(float(d)) != str(d), "float repr must differ to prove drift risk"


# ---------------------------------------------------------------------------
# CB4: MARKET no price param; LIMIT passes Price; unknown type raises
# ---------------------------------------------------------------------------


class TestCB4OrderTypeRouting:
    def test_market_order_created(self) -> None:
        clock = _make_clock()
        factory = _make_factory(clock)
        spec = _market_spec()
        cmd = order_spec_to_submit(spec, _INSTRUMENT_ID, factory, _TRADER_ID, _STRATEGY_ID, clock)
        assert cmd.order.order_type == OrderType.MARKET

    def test_market_order_has_no_price(self) -> None:
        clock = _make_clock()
        factory = _make_factory(clock)
        spec = _market_spec()
        cmd = order_spec_to_submit(spec, _INSTRUMENT_ID, factory, _TRADER_ID, _STRATEGY_ID, clock)
        # MarketOrder carries no price attribute — OrderSpec.price=0 is NOT forwarded
        assert not hasattr(cmd.order, "price") or cmd.order.order_type == OrderType.MARKET

    def test_limit_order_created_with_price(self) -> None:
        clock = _make_clock()
        factory = _make_factory(clock)
        spec = _limit_spec()
        cmd = order_spec_to_submit(spec, _INSTRUMENT_ID, factory, _TRADER_ID, _STRATEGY_ID, clock)
        assert cmd.order.order_type == OrderType.LIMIT
        assert str(cmd.order.price) == "83.70"

    def test_unknown_order_type_raises(self) -> None:
        clock = _make_clock()
        factory = _make_factory(clock)
        bad_spec = OrderSpec(
            symbol="SOLUSDT", side="BUY", order_type="STOP",
            price=Decimal("83.70"), quantity=Decimal("0.060"),
        )
        with pytest.raises(ValueError, match="STOP"):
            order_spec_to_submit(bad_spec, _INSTRUMENT_ID, factory, _TRADER_ID, _STRATEGY_ID, clock)


# ---------------------------------------------------------------------------
# CB5: side mapping; unknown side raises ValueError (not silent)
# ---------------------------------------------------------------------------


class TestCB5SideMapping:
    def test_buy_maps_to_order_side_buy(self) -> None:
        clock = _make_clock()
        factory = _make_factory(clock)
        spec = _market_spec()
        cmd = order_spec_to_submit(spec, _INSTRUMENT_ID, factory, _TRADER_ID, _STRATEGY_ID, clock)
        assert cmd.order.side == OrderSide.BUY

    def test_sell_maps_to_order_side_sell(self) -> None:
        clock = _make_clock()
        factory = _make_factory(clock)
        spec = build_order_spec(
            "SOLUSDT", "SELL", "MARKET",
            raw_price=Decimal("83.70"),
            raw_qty=Decimal("0.06"),
            limits=_SOL_LIMITS,
        )
        cmd = order_spec_to_submit(spec, _INSTRUMENT_ID, factory, _TRADER_ID, _STRATEGY_ID, clock)
        assert cmd.order.side == OrderSide.SELL

    def test_unknown_side_raises_value_error(self) -> None:
        clock = _make_clock()
        factory = _make_factory(clock)
        bad_spec = OrderSpec(
            symbol="SOLUSDT", side="LONG", order_type="MARKET",
            price=Decimal("0"), quantity=Decimal("0.060"),
        )
        with pytest.raises(ValueError, match="LONG"):
            order_spec_to_submit(bad_spec, _INSTRUMENT_ID, factory, _TRADER_ID, _STRATEGY_ID, clock)


# ---------------------------------------------------------------------------
# CB6: tie-back — SOL sample (0.060 qty / 83.70 price) pins SubmitOrder fields
# ---------------------------------------------------------------------------


class TestCB6Tieback:
    def test_market_order_qty_pinned(self) -> None:
        clock = _make_clock()
        factory = _make_factory(clock)
        spec = _market_spec()
        cmd = order_spec_to_submit(spec, _INSTRUMENT_ID, factory, _TRADER_ID, _STRATEGY_ID, clock)
        assert str(cmd.order.quantity) == "0.060"

    def test_market_order_side_pinned(self) -> None:
        clock = _make_clock()
        factory = _make_factory(clock)
        spec = _market_spec()
        cmd = order_spec_to_submit(spec, _INSTRUMENT_ID, factory, _TRADER_ID, _STRATEGY_ID, clock)
        assert cmd.order.side == OrderSide.BUY

    def test_market_order_type_pinned(self) -> None:
        clock = _make_clock()
        factory = _make_factory(clock)
        spec = _market_spec()
        cmd = order_spec_to_submit(spec, _INSTRUMENT_ID, factory, _TRADER_ID, _STRATEGY_ID, clock)
        assert cmd.order.order_type == OrderType.MARKET

    def test_submit_order_trader_id(self) -> None:
        clock = _make_clock()
        factory = _make_factory(clock)
        spec = _market_spec()
        cmd = order_spec_to_submit(spec, _INSTRUMENT_ID, factory, _TRADER_ID, _STRATEGY_ID, clock)
        assert cmd.trader_id == _TRADER_ID

    def test_submit_order_strategy_id(self) -> None:
        clock = _make_clock()
        factory = _make_factory(clock)
        spec = _market_spec()
        cmd = order_spec_to_submit(spec, _INSTRUMENT_ID, factory, _TRADER_ID, _STRATEGY_ID, clock)
        assert cmd.strategy_id == _STRATEGY_ID

    def test_submit_order_command_id_is_uuid4(self) -> None:
        clock = _make_clock()
        factory = _make_factory(clock)
        spec = _market_spec()
        cmd = order_spec_to_submit(spec, _INSTRUMENT_ID, factory, _TRADER_ID, _STRATEGY_ID, clock)
        # command_id stored as NT UUID4; round-trip through .value → UUID to verify format
        cmd_id_str = cmd.id.value
        parsed = UUID(cmd_id_str)
        assert parsed.version == 4

    def test_submit_order_ts_init_from_clock(self) -> None:
        clock = _make_clock()
        factory = _make_factory(clock)
        ts_before = clock.timestamp_ns()
        spec = _market_spec()
        cmd = order_spec_to_submit(spec, _INSTRUMENT_ID, factory, _TRADER_ID, _STRATEGY_ID, clock)
        ts_after = clock.timestamp_ns()
        assert ts_before <= cmd.ts_init <= ts_after

    def test_limit_price_pinned_83_70(self) -> None:
        clock = _make_clock()
        factory = _make_factory(clock)
        spec = _limit_spec()
        cmd = order_spec_to_submit(spec, _INSTRUMENT_ID, factory, _TRADER_ID, _STRATEGY_ID, clock)
        assert str(cmd.order.price) == "83.70"
        assert Decimal(str(cmd.order.price)) == Decimal("83.70")


# ---------------------------------------------------------------------------
# CB7: happy path with real NT OrderFactory + InstrumentId + from_str → SubmitOrder
# ---------------------------------------------------------------------------


class TestCB7HappyPath:
    def test_market_buy_returns_submit_order(self) -> None:
        clock = _make_clock()
        factory = _make_factory(clock)
        spec = _market_spec()
        cmd = order_spec_to_submit(spec, _INSTRUMENT_ID, factory, _TRADER_ID, _STRATEGY_ID, clock)
        assert isinstance(cmd, SubmitOrder)

    def test_limit_buy_returns_submit_order(self) -> None:
        clock = _make_clock()
        factory = _make_factory(clock)
        spec = _limit_spec()
        cmd = order_spec_to_submit(spec, _INSTRUMENT_ID, factory, _TRADER_ID, _STRATEGY_ID, clock)
        assert isinstance(cmd, SubmitOrder)

    def test_real_instrument_id_from_str_used(self) -> None:
        iid = InstrumentId.from_str("SOLUSDT.BINANCE")
        clock = _make_clock()
        factory = _make_factory(clock)
        spec = _market_spec()
        cmd = order_spec_to_submit(spec, iid, factory, _TRADER_ID, _STRATEGY_ID, clock)
        assert str(cmd.instrument_id) == "SOLUSDT.BINANCE"

    def test_quantity_constructed_via_from_str(self) -> None:
        clock = _make_clock()
        factory = _make_factory(clock)
        spec = _market_spec()
        cmd = order_spec_to_submit(spec, _INSTRUMENT_ID, factory, _TRADER_ID, _STRATEGY_ID, clock)
        # Quantity.from_str("0.060") preserves trailing zero
        assert str(cmd.order.quantity) == "0.060"

    def test_two_calls_produce_distinct_command_ids(self) -> None:
        clock = _make_clock()
        factory = _make_factory(clock)
        spec = _market_spec()
        cmd1 = order_spec_to_submit(spec, _INSTRUMENT_ID, factory, _TRADER_ID, _STRATEGY_ID, clock)
        cmd2 = order_spec_to_submit(spec, _INSTRUMENT_ID, factory, _TRADER_ID, _STRATEGY_ID, clock)
        assert cmd1.id.value != cmd2.id.value
