"""Unit tests for hermes.execution.precision.

All arithmetic uses Decimal exclusively — no float on price/qty paths.
SOLUSDT testnet parameters used throughout:
    tick=0.01, step=0.001, min_notional=5, qty_max=90000,
    percent multipliers: bid 0.5/2.0, ask 0.5/2.0
"""

from decimal import Decimal

import pytest

from hermes.execution.precision import (
    InstrumentLimits,
    OrderRejected,
    OrderSpec,
    build_order_spec,
    check_notional,
    check_percent_price,
    floor_to_step,
    floor_to_tick,
    round_price,
    round_quantity,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def sol_limits(
    *,
    apply_min_to_market: bool = True,
    bid_up: str = "2.0",
    bid_down: str = "0.5",
    ask_up: str = "2.0",
    ask_down: str = "0.5",
    price_min: str = "0",
    price_max: str = "0",
) -> InstrumentLimits:
    return InstrumentLimits(
        price_tick=Decimal("0.01"),
        price_min=Decimal(price_min),
        price_max=Decimal(price_max),
        qty_step=Decimal("0.001"),
        qty_min=Decimal("0.001"),
        qty_max=Decimal("90000"),
        min_notional=Decimal("5"),
        apply_min_to_market=apply_min_to_market,
        bid_multiplier_up=Decimal(bid_up),
        bid_multiplier_down=Decimal(bid_down),
        ask_multiplier_up=Decimal(ask_up),
        ask_multiplier_down=Decimal(ask_down),
    )


# ---------------------------------------------------------------------------
# floor_to_tick
# ---------------------------------------------------------------------------


class TestFloorToTick:
    def test_basic_floor(self):
        assert floor_to_tick(Decimal("123.456"), Decimal("0.01")) == Decimal("123.45")

    def test_exact_multiple_unchanged(self):
        assert floor_to_tick(Decimal("123.45"), Decimal("0.01")) == Decimal("123.45")

    def test_just_below_next_tick(self):
        # 1.019 should floor to 1.01, not round to 1.02
        assert floor_to_tick(Decimal("1.019"), Decimal("0.01")) == Decimal("1.01")

    def test_just_above_tick(self):
        assert floor_to_tick(Decimal("1.011"), Decimal("0.01")) == Decimal("1.01")

    def test_whole_number_tick(self):
        assert floor_to_tick(Decimal("150.7"), Decimal("1")) == Decimal("150")

    def test_sub_cent_tick(self):
        assert floor_to_tick(Decimal("0.12345"), Decimal("0.001")) == Decimal("0.123")

    def test_zero_value(self):
        assert floor_to_tick(Decimal("0"), Decimal("0.01")) == Decimal("0.00")

    def test_large_value(self):
        assert floor_to_tick(Decimal("99999.999"), Decimal("0.01")) == Decimal("99999.99")

    def test_zero_tick_raises(self):
        with pytest.raises(ValueError, match="tick must be positive"):
            floor_to_tick(Decimal("1.0"), Decimal("0"))

    def test_negative_tick_raises(self):
        with pytest.raises(ValueError, match="tick must be positive"):
            floor_to_tick(Decimal("1.0"), Decimal("-0.01"))

    def test_no_float_contamination(self):
        # Classic float trap: 0.1 + 0.2 != 0.3 in float world
        result = floor_to_tick(Decimal("0.3"), Decimal("0.1"))
        assert result == Decimal("0.3")

    def test_decimal_addition_exact(self):
        # Decimal("0.1") + Decimal("0.2") must equal Decimal("0.3") exactly
        assert Decimal("0.1") + Decimal("0.2") == Decimal("0.3")


class TestFloorToStep:
    def test_qty_floor(self):
        assert floor_to_step(Decimal("1.5678"), Decimal("0.001")) == Decimal("1.567")

    def test_exact_step(self):
        assert floor_to_step(Decimal("1.500"), Decimal("0.001")) == Decimal("1.500")

    def test_just_below_next_step(self):
        assert floor_to_step(Decimal("0.0019"), Decimal("0.001")) == Decimal("0.001")


# ---------------------------------------------------------------------------
# round_price / round_quantity
# ---------------------------------------------------------------------------


class TestRoundPriceAndQuantity:
    def test_round_price(self):
        lim = sol_limits()
        assert round_price(Decimal("150.756"), lim) == Decimal("150.75")

    def test_round_quantity(self):
        lim = sol_limits()
        assert round_quantity(Decimal("1.2349"), lim) == Decimal("1.234")

    def test_price_already_on_tick(self):
        lim = sol_limits()
        assert round_price(Decimal("150.75"), lim) == Decimal("150.75")

    def test_qty_already_on_step(self):
        lim = sol_limits()
        assert round_quantity(Decimal("1.234"), lim) == Decimal("1.234")


# ---------------------------------------------------------------------------
# check_notional
# ---------------------------------------------------------------------------


class TestCheckNotional:
    def test_passes_above_min(self):
        lim = sol_limits()
        check_notional(Decimal("150"), Decimal("0.1"), lim)  # 15 >= 5

    def test_exact_min_passes(self):
        lim = sol_limits()
        # 5.00 / 150 = 0.0333... → use simpler: 5 / 1 = 5
        check_notional(Decimal("5"), Decimal("1"), lim)

    def test_below_min_raises(self):
        lim = sol_limits()
        with pytest.raises(OrderRejected, match="notional"):
            check_notional(Decimal("1"), Decimal("1"), lim)  # 1 < 5

    def test_market_skip_when_not_applied(self):
        lim = sol_limits(apply_min_to_market=False)
        # Would fail notional check but flag prevents it
        check_notional(Decimal("1"), Decimal("1"), lim, is_market=True)

    def test_market_enforced_when_applied(self):
        lim = sol_limits(apply_min_to_market=True)
        with pytest.raises(OrderRejected):
            check_notional(Decimal("1"), Decimal("1"), lim, is_market=True)


# ---------------------------------------------------------------------------
# check_percent_price
# ---------------------------------------------------------------------------


class TestCheckPercentPrice:
    def test_buy_within_band(self):
        lim = sol_limits()
        # avg=100, band=[50,200]; price=100 passes
        check_percent_price(Decimal("100"), "BUY", lim, Decimal("100"))

    def test_buy_at_lower_bound(self):
        # avg=100, bid_down=0.5 → lower=50; price=50 should pass
        lim = sol_limits()
        check_percent_price(Decimal("50"), "BUY", lim, Decimal("100"))

    def test_buy_at_upper_bound(self):
        # avg=100, bid_up=2.0 → upper=200; price=200 should pass
        lim = sol_limits()
        check_percent_price(Decimal("200"), "BUY", lim, Decimal("100"))

    def test_buy_below_lower_bound_rejected(self):
        lim = sol_limits()
        with pytest.raises(OrderRejected, match="PERCENT_PRICE"):
            check_percent_price(Decimal("49.99"), "BUY", lim, Decimal("100"))

    def test_buy_above_upper_bound_rejected(self):
        lim = sol_limits()
        with pytest.raises(OrderRejected, match="PERCENT_PRICE"):
            check_percent_price(Decimal("200.01"), "BUY", lim, Decimal("100"))

    def test_sell_within_band(self):
        lim = sol_limits()
        check_percent_price(Decimal("100"), "SELL", lim, Decimal("100"))

    def test_sell_below_lower_rejected(self):
        lim = sol_limits()
        with pytest.raises(OrderRejected):
            check_percent_price(Decimal("49.99"), "SELL", lim, Decimal("100"))

    def test_sell_above_upper_rejected(self):
        lim = sol_limits()
        with pytest.raises(OrderRejected):
            check_percent_price(Decimal("200.01"), "SELL", lim, Decimal("100"))

    def test_avg_price_none_skips_check(self):
        lim = sol_limits()
        # Would be way outside band if applied, but avg_price=None skips
        check_percent_price(Decimal("999999"), "BUY", lim, None)

    def test_unknown_side_raises(self):
        lim = sol_limits()
        with pytest.raises(ValueError, match="Unknown side"):
            check_percent_price(Decimal("100"), "HOLD", lim, Decimal("100"))

    def test_asymmetric_multipliers(self):
        # bid band 0.8-1.1, ask band 0.9-1.2
        lim = InstrumentLimits(
            price_tick=Decimal("0.01"),
            price_min=Decimal("0"),
            price_max=Decimal("0"),
            qty_step=Decimal("0.001"),
            qty_min=Decimal("0.001"),
            qty_max=Decimal("90000"),
            min_notional=Decimal("5"),
            apply_min_to_market=True,
            bid_multiplier_up=Decimal("1.1"),
            bid_multiplier_down=Decimal("0.8"),
            ask_multiplier_up=Decimal("1.2"),
            ask_multiplier_down=Decimal("0.9"),
        )
        # BUY at 110 (=100*1.1) passes; 110.01 fails
        check_percent_price(Decimal("110"), "BUY", lim, Decimal("100"))
        with pytest.raises(OrderRejected):
            check_percent_price(Decimal("110.01"), "BUY", lim, Decimal("100"))
        # SELL at 120 (=100*1.2) passes; 120.01 fails
        check_percent_price(Decimal("120"), "SELL", lim, Decimal("100"))
        with pytest.raises(OrderRejected):
            check_percent_price(Decimal("120.01"), "SELL", lim, Decimal("100"))


# ---------------------------------------------------------------------------
# build_order_spec — happy path
# ---------------------------------------------------------------------------


class TestBuildOrderSpecHappyPath:
    def test_limit_buy_basic(self):
        lim = sol_limits()
        spec = build_order_spec(
            "SOLUSDT", "BUY", "LIMIT",
            Decimal("150.756"), Decimal("0.1234"),
            lim, avg_price=Decimal("150"),
        )
        assert spec.price == Decimal("150.75")
        assert spec.quantity == Decimal("0.123")
        assert spec.side == "BUY"
        assert spec.order_type == "LIMIT"
        assert spec.symbol == "SOLUSDT"

    def test_limit_sell_basic(self):
        lim = sol_limits()
        spec = build_order_spec(
            "SOLUSDT", "SELL", "LIMIT",
            Decimal("149.999"), Decimal("0.1"),
            lim, avg_price=Decimal("150"),
        )
        assert spec.price == Decimal("149.99")
        assert spec.quantity == Decimal("0.100")

    def test_market_buy(self):
        lim = sol_limits()
        spec = build_order_spec(
            "SOLUSDT", "BUY", "MARKET",
            Decimal("150"), Decimal("0.1"),
            lim,
        )
        assert spec.price == Decimal(0)
        assert spec.order_type == "MARKET"

    def test_market_no_percent_price_check(self):
        # price that would fail percent check should be ignored for MARKET
        lim = sol_limits()
        spec = build_order_spec(
            "SOLUSDT", "BUY", "MARKET",
            Decimal("999"), Decimal("0.1"),
            lim, avg_price=Decimal("100"),
        )
        assert spec.order_type == "MARKET"

    def test_side_case_insensitive(self):
        lim = sol_limits()
        spec = build_order_spec(
            "SOLUSDT", "buy", "limit",
            Decimal("150"), Decimal("0.1"),
            lim,
        )
        assert spec.side == "BUY"
        assert spec.order_type == "LIMIT"

    def test_floor_not_round(self):
        # 0.0199 should floor to 0.019, not round to 0.020
        # Use price=1000 so notional=19 >= min_notional=5
        lim = sol_limits()
        spec = build_order_spec(
            "SOLUSDT", "BUY", "LIMIT",
            Decimal("1000.00"), Decimal("0.0199"),
            lim, avg_price=Decimal("1000"),
        )
        assert spec.quantity == Decimal("0.019")


# ---------------------------------------------------------------------------
# build_order_spec — rejection cases
# ---------------------------------------------------------------------------


class TestBuildOrderSpecRejection:
    def test_qty_below_min_rejected(self):
        lim = sol_limits()
        with pytest.raises(OrderRejected, match="qty_min"):
            build_order_spec(
                "SOLUSDT", "BUY", "LIMIT",
                Decimal("150"), Decimal("0.0009"),
                lim,
            )

    def test_qty_floors_to_zero_rejected(self):
        # 0.0001 floors to 0.000 with step=0.001 → below qty_min
        lim = sol_limits()
        with pytest.raises(OrderRejected, match="qty_min"):
            build_order_spec(
                "SOLUSDT", "BUY", "LIMIT",
                Decimal("150"), Decimal("0.0001"),
                lim,
            )

    def test_qty_above_max_rejected(self):
        lim = sol_limits()
        with pytest.raises(OrderRejected, match="qty_max"):
            build_order_spec(
                "SOLUSDT", "BUY", "LIMIT",
                Decimal("150"), Decimal("90001"),
                lim,
            )

    def test_notional_below_min_rejected(self):
        lim = sol_limits()
        # price=1.00, qty=0.001 → notional=0.001 < 5
        with pytest.raises(OrderRejected, match="notional"):
            build_order_spec(
                "SOLUSDT", "BUY", "LIMIT",
                Decimal("1.00"), Decimal("0.001"),
                lim,
            )

    def test_price_above_max_rejected(self):
        lim = sol_limits(price_max="200")
        with pytest.raises(OrderRejected, match="price_max"):
            build_order_spec(
                "SOLUSDT", "BUY", "LIMIT",
                Decimal("201"), Decimal("1"),
                lim,
            )

    def test_price_below_min_rejected(self):
        lim = sol_limits(price_min="100")
        with pytest.raises(OrderRejected, match="price_min"):
            build_order_spec(
                "SOLUSDT", "BUY", "LIMIT",
                Decimal("99"), Decimal("1"),
                lim,
            )

    def test_percent_price_violation_rejected_not_clamped(self):
        lim = sol_limits()
        # avg=100, upper=200; price=250 → rejected, NOT silently clamped
        with pytest.raises(OrderRejected, match="PERCENT_PRICE"):
            build_order_spec(
                "SOLUSDT", "BUY", "LIMIT",
                Decimal("250"), Decimal("1"),
                lim, avg_price=Decimal("100"),
            )

    def test_percent_price_below_lower_rejected(self):
        lim = sol_limits()
        # avg=100, lower=50; price=49 → rejected
        with pytest.raises(OrderRejected, match="PERCENT_PRICE"):
            build_order_spec(
                "SOLUSDT", "BUY", "LIMIT",
                Decimal("49"), Decimal("1"),
                lim, avg_price=Decimal("100"),
            )

    def test_market_notional_skip_when_not_applied(self):
        lim = sol_limits(apply_min_to_market=False)
        # notional=0.001 < 5, but apply_min_to_market=False for MARKET
        spec = build_order_spec(
            "SOLUSDT", "BUY", "MARKET",
            Decimal("1.00"), Decimal("0.001"),
            lim,
        )
        assert spec.quantity == Decimal("0.001")

    def test_market_notional_enforced_when_applied(self):
        lim = sol_limits(apply_min_to_market=True)
        with pytest.raises(OrderRejected, match="notional"):
            build_order_spec(
                "SOLUSDT", "BUY", "MARKET",
                Decimal("1.00"), Decimal("0.001"),
                lim,
            )


# ---------------------------------------------------------------------------
# SOLUSDT testnet exact inputs
# ---------------------------------------------------------------------------


class TestSolUsdtTestnet:
    """Regression tests using real SOLUSDT testnet filter values."""

    def test_standard_limit_buy(self):
        lim = sol_limits()
        spec = build_order_spec(
            "SOLUSDT", "BUY", "LIMIT",
            Decimal("147.325"), Decimal("0.0345"),
            lim, avg_price=Decimal("147"),
        )
        assert spec.price == Decimal("147.32")
        assert spec.quantity == Decimal("0.034")

    def test_notional_exactly_at_min(self):
        lim = sol_limits()
        # price=100.00, qty=0.05 → notional=5.00 == min_notional → passes
        spec = build_order_spec(
            "SOLUSDT", "BUY", "LIMIT",
            Decimal("100.00"), Decimal("0.05"),
            lim, avg_price=Decimal("100"),
        )
        assert spec.price == Decimal("100.00")
        assert spec.quantity == Decimal("0.050")

    def test_percent_price_band_boundary_buy(self):
        lim = sol_limits()
        # avg=150, band=[75, 300]; price=75 passes, price=74.99 fails
        spec = build_order_spec(
            "SOLUSDT", "BUY", "LIMIT",
            Decimal("75.00"), Decimal("0.1"),
            lim, avg_price=Decimal("150"),
        )
        assert spec.price == Decimal("75.00")
        with pytest.raises(OrderRejected):
            build_order_spec(
                "SOLUSDT", "BUY", "LIMIT",
                Decimal("74.99"), Decimal("0.1"),
                lim, avg_price=Decimal("150"),
            )

    def test_qty_at_max_boundary(self):
        lim = sol_limits()
        spec = build_order_spec(
            "SOLUSDT", "BUY", "LIMIT",
            Decimal("150"), Decimal("90000"),
            lim, avg_price=Decimal("150"),
        )
        assert spec.quantity == Decimal("90000.000")

    def test_qty_exceeds_max_rejected(self):
        lim = sol_limits()
        with pytest.raises(OrderRejected, match="qty_max"):
            build_order_spec(
                "SOLUSDT", "BUY", "LIMIT",
                Decimal("150"), Decimal("90000.001"),
                lim, avg_price=Decimal("150"),
            )


# ---------------------------------------------------------------------------
# Edge cases and robustness
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_zero_step_raises(self):
        with pytest.raises(ValueError, match="tick must be positive"):
            floor_to_tick(Decimal("1"), Decimal("0"))

    def test_extreme_large_qty(self):
        lim = InstrumentLimits(
            price_tick=Decimal("0.01"),
            price_min=Decimal("0"),
            price_max=Decimal("0"),
            qty_step=Decimal("1"),
            qty_min=Decimal("1"),
            qty_max=Decimal("10000000"),
            min_notional=Decimal("1"),
            apply_min_to_market=True,
            bid_multiplier_up=Decimal("2"),
            bid_multiplier_down=Decimal("0.5"),
            ask_multiplier_up=Decimal("2"),
            ask_multiplier_down=Decimal("0.5"),
        )
        spec = build_order_spec(
            "BIGTOKEN", "BUY", "LIMIT",
            Decimal("1.00"), Decimal("9999999.99"),
            lim,
        )
        assert spec.quantity == Decimal("9999999")

    def test_price_min_zero_not_enforced(self):
        # price_min=0 means not enforced — very small price should pass
        lim = sol_limits(price_min="0")
        spec = build_order_spec(
            "SOLUSDT", "BUY", "LIMIT",
            Decimal("0.01"), Decimal("1000"),
            lim,
        )
        assert spec.price == Decimal("0.01")

    def test_price_max_zero_not_enforced(self):
        lim = sol_limits(price_max="0")
        spec = build_order_spec(
            "SOLUSDT", "BUY", "LIMIT",
            Decimal("999999.00"), Decimal("0.01"),
            lim, avg_price=Decimal("999999"),
        )
        assert spec.price == Decimal("999999.00")

    def test_order_spec_is_frozen(self):
        spec = OrderSpec(
            symbol="SOLUSDT",
            side="BUY",
            order_type="LIMIT",
            price=Decimal("150"),
            quantity=Decimal("1"),
        )
        with pytest.raises((AttributeError, TypeError)):
            spec.price = Decimal("200")  # type: ignore[misc]

    def test_instrument_limits_is_frozen(self):
        lim = sol_limits()
        with pytest.raises((AttributeError, TypeError)):
            lim.price_tick = Decimal("0.001")  # type: ignore[misc]
