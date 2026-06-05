"""Tests for compute_far_limit_buy (T1–T7)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from hermes.execution.far_limit import compute_far_limit_buy


class TestT1MarginApplied:
    def test_basic_values(self) -> None:
        # avg=100, bid_mult_down=0.5 → ppbs_lower=50, raw=50.05, tick-aligned=50.05
        result = compute_far_limit_buy(
            avg=Decimal("100"),
            bid_multiplier_down=Decimal("0.5"),
            tick=Decimal("0.01"),
            safety_margin=Decimal("0.001"),
        )
        assert result == Decimal("50.05")

    def test_default_margin_matches_explicit(self) -> None:
        explicit = compute_far_limit_buy(
            avg=Decimal("100"),
            bid_multiplier_down=Decimal("0.5"),
            tick=Decimal("0.01"),
            safety_margin=Decimal("0.001"),
        )
        default = compute_far_limit_buy(
            avg=Decimal("100"),
            bid_multiplier_down=Decimal("0.5"),
            tick=Decimal("0.01"),
        )
        assert explicit == default


class TestT2FloorDirection:
    def test_raw_between_ticks_floors_down(self) -> None:
        # avg=100, bid_mult_down=0.5, margin=0 → raw=50.000; shift avg slightly
        # avg=100.03, bid_mult_down=0.5, margin=0 → raw=50.015 → floor to 50.01
        result = compute_far_limit_buy(
            avg=Decimal("100.03"),
            bid_multiplier_down=Decimal("0.5"),
            tick=Decimal("0.01"),
            safety_margin=Decimal("0"),
        )
        assert result == Decimal("50.01")

    def test_not_ceiling(self) -> None:
        # Confirm floor, not ceiling: raw=50.015 → 50.01 (not 50.02)
        result = compute_far_limit_buy(
            avg=Decimal("100.03"),
            bid_multiplier_down=Decimal("0.5"),
            tick=Decimal("0.01"),
            safety_margin=Decimal("0"),
        )
        assert result < Decimal("50.02")


class TestT3MarginZero:
    def test_zero_margin_is_pure_ppbs_floor(self) -> None:
        # avg=200, bid_mult_down=0.5 → ppbs_lower=100.00, floor(100.00, 0.01)=100.00
        result = compute_far_limit_buy(
            avg=Decimal("200"),
            bid_multiplier_down=Decimal("0.5"),
            tick=Decimal("0.01"),
            safety_margin=Decimal("0"),
        )
        assert result == Decimal("100.00")


class TestT4CustomMargin:
    def test_half_percent_margin(self) -> None:
        # avg=100, bid_mult_down=0.5, margin=0.005
        # ppbs_lower=50, raw=50.25, floor(50.25, 0.01)=50.25
        result = compute_far_limit_buy(
            avg=Decimal("100"),
            bid_multiplier_down=Decimal("0.5"),
            tick=Decimal("0.01"),
            safety_margin=Decimal("0.005"),
        )
        assert result == Decimal("50.25")


class TestT5ReturnTypeDecimal:
    def test_return_type_is_decimal(self) -> None:
        result = compute_far_limit_buy(
            avg=Decimal("100"),
            bid_multiplier_down=Decimal("0.5"),
            tick=Decimal("0.01"),
        )
        assert type(result) is Decimal


class TestT6InvalidInputsRaise:
    def test_avg_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="avg"):
            compute_far_limit_buy(
                avg=Decimal("0"),
                bid_multiplier_down=Decimal("0.5"),
                tick=Decimal("0.01"),
            )

    def test_avg_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="avg"):
            compute_far_limit_buy(
                avg=Decimal("-1"),
                bid_multiplier_down=Decimal("0.5"),
                tick=Decimal("0.01"),
            )

    def test_bid_multiplier_down_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="bid_multiplier_down"):
            compute_far_limit_buy(
                avg=Decimal("100"),
                bid_multiplier_down=Decimal("0"),
                tick=Decimal("0.01"),
            )

    def test_bid_multiplier_down_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="bid_multiplier_down"):
            compute_far_limit_buy(
                avg=Decimal("100"),
                bid_multiplier_down=Decimal("-0.5"),
                tick=Decimal("0.01"),
            )

    def test_tick_zero_propagates_from_floor_to_tick(self) -> None:
        with pytest.raises(ValueError):
            compute_far_limit_buy(
                avg=Decimal("100"),
                bid_multiplier_down=Decimal("0.5"),
                tick=Decimal("0"),
            )


class TestT7TiebackSOL:
    def test_sol_result_above_ppbs_lower_and_below_avg(self) -> None:
        # SOL testnet: bid_mult_down=0.5, tick=0.01, avg=83.70 (E3.1 live ref)
        # ppbs_lower = 83.70 * 0.5 = 41.85
        # raw_far    = 41.85 * 1.001 = 41.8919 → floor → 41.89
        # Invariant: ppbs_lower <= far_limit < avg
        #   - >= ppbs_lower: order accepted by Binance PPBS filter
        #   - <  avg:        far from market (unlikely to fill)
        avg = Decimal("83.70")
        bid_mult_down = Decimal("0.5")
        tick = Decimal("0.01")
        ppbs_lower = avg * bid_mult_down  # = 41.85

        result = compute_far_limit_buy(
            avg=avg,
            bid_multiplier_down=bid_mult_down,
            tick=tick,
        )
        assert result >= ppbs_lower, f"far-limit {result} below PPBS lower bound {ppbs_lower}"
        assert result < avg, f"far-limit {result} not far from avg {avg}"

    def test_sol_result_tick_aligned(self) -> None:
        tick = Decimal("0.01")
        result = compute_far_limit_buy(
            avg=Decimal("83.70"),
            bid_multiplier_down=Decimal("0.5"),
            tick=tick,
        )
        # Result must be an exact multiple of tick
        assert result % tick == Decimal("0")

    def test_sol_result_positive(self) -> None:
        result = compute_far_limit_buy(
            avg=Decimal("83.70"),
            bid_multiplier_down=Decimal("0.5"),
            tick=Decimal("0.01"),
        )
        assert result > Decimal("0")
