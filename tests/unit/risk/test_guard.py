"""Unit tests for RiskGuard — CR1~CR8 coverage."""

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from hermes.risk.guard import GuardState, RiskDenied, RiskGuard


# ---------------------------------------------------------------------------
# CR2: Killswitch state machine — 3 dedicated tests
# ---------------------------------------------------------------------------


class TestKillswitchStateMachine:
    def test_initial_state_is_active(self):
        guard = RiskGuard(consecutive_loss_limit=3, on_halt=lambda: None)
        assert guard.state is GuardState.ACTIVE

    def test_halt_transitions_to_halted(self):
        guard = RiskGuard(consecutive_loss_limit=3, on_halt=lambda: None)
        guard.halt()
        assert guard.state is GuardState.HALTED

    def test_halted_does_not_recover_on_profit(self):
        guard = RiskGuard(consecutive_loss_limit=3, on_halt=lambda: None)
        guard.halt()
        guard.on_trade_result(Decimal("100"))
        assert guard.state is GuardState.HALTED


# ---------------------------------------------------------------------------
# CR3: check_order gate — 2 dedicated tests
# ---------------------------------------------------------------------------


class TestCheckOrder:
    def test_active_passes_without_raise(self):
        guard = RiskGuard(consecutive_loss_limit=3, on_halt=lambda: None)
        guard.check_order()  # must not raise

    def test_halted_raises_risk_denied_with_readable_reason(self):
        guard = RiskGuard(consecutive_loss_limit=3, on_halt=lambda: None)
        guard.halt()
        with pytest.raises(RiskDenied) as exc_info:
            guard.check_order()
        assert exc_info.value.reason
        assert isinstance(exc_info.value, RiskDenied)


# ---------------------------------------------------------------------------
# CR4: Consecutive-loss boundary — 4 dedicated tests, off-by-one nailed
# ---------------------------------------------------------------------------


class TestConsecutiveLossBoundary:
    """All tests use N=3 for concrete, readable assertions."""

    N = 3

    def _guard(self) -> RiskGuard:
        return RiskGuard(consecutive_loss_limit=self.N, on_halt=lambda: None)

    def test_n_minus_1_losses_do_not_halt(self):
        guard = self._guard()
        for _ in range(self.N - 1):  # 2 losses
            guard.on_trade_result(Decimal("-1"))
        assert guard.state is GuardState.ACTIVE
        assert guard.consecutive_losses == self.N - 1

    def test_nth_loss_triggers_halt(self):
        guard = self._guard()
        for _ in range(self.N):  # 3 losses → halt
            guard.on_trade_result(Decimal("-1"))
        assert guard.state is GuardState.HALTED

    def test_zero_pnl_after_n_minus_1_resets_counter(self):
        guard = self._guard()
        for _ in range(self.N - 1):
            guard.on_trade_result(Decimal("-1"))
        guard.on_trade_result(Decimal("0"))
        assert guard.consecutive_losses == 0
        assert guard.state is GuardState.ACTIVE

    def test_positive_pnl_after_n_minus_1_resets_counter(self):
        guard = self._guard()
        for _ in range(self.N - 1):
            guard.on_trade_result(Decimal("-1"))
        guard.on_trade_result(Decimal("0.01"))
        assert guard.consecutive_losses == 0
        assert guard.state is GuardState.ACTIVE


# ---------------------------------------------------------------------------
# CR5: on_halt callback spy — 2 dedicated tests
# ---------------------------------------------------------------------------


class TestOnHaltCallback:
    def test_first_trigger_calls_callback_once(self):
        callback = MagicMock()
        guard = RiskGuard(consecutive_loss_limit=2, on_halt=callback)
        guard.on_trade_result(Decimal("-1"))
        guard.on_trade_result(Decimal("-1"))
        callback.assert_called_once()

    def test_no_repeated_callback_when_already_halted(self):
        callback = MagicMock()
        guard = RiskGuard(consecutive_loss_limit=2, on_halt=callback)
        guard.on_trade_result(Decimal("-1"))
        guard.on_trade_result(Decimal("-1"))
        assert callback.call_count == 1
        # Additional losses after halt must not fire callback again
        guard.on_trade_result(Decimal("-1"))
        guard.on_trade_result(Decimal("-5"))
        assert callback.call_count == 1


# ---------------------------------------------------------------------------
# CR6: Decimal pnl sign semantics — 3 dedicated tests
# ---------------------------------------------------------------------------


class TestDecimalPnlSemantics:
    def test_small_negative_decimal_counts_as_loss(self):
        guard = RiskGuard(consecutive_loss_limit=5, on_halt=lambda: None)
        guard.on_trade_result(Decimal("-0.01"))
        assert guard.consecutive_losses == 1

    def test_zero_decimal_does_not_count_as_loss(self):
        guard = RiskGuard(consecutive_loss_limit=5, on_halt=lambda: None)
        guard.on_trade_result(Decimal("-0.01"))  # loss first
        guard.on_trade_result(Decimal("0"))      # resets, not a loss
        assert guard.consecutive_losses == 0

    def test_small_positive_decimal_does_not_count_as_loss(self):
        guard = RiskGuard(consecutive_loss_limit=5, on_halt=lambda: None)
        guard.on_trade_result(Decimal("-0.01"))  # loss first
        guard.on_trade_result(Decimal("0.01"))   # resets, not a loss
        assert guard.consecutive_losses == 0


# ---------------------------------------------------------------------------
# CD3: Daily drawdown threshold semantics — 3 tests
# ---------------------------------------------------------------------------


class TestDailyDrawdownThreshold:
    """daily_drawdown_limit is a positive Decimal; cumulative <= -limit triggers halt."""

    def _guard(self, limit: str = "100") -> RiskGuard:
        return RiskGuard(
            consecutive_loss_limit=99,
            on_halt=lambda: None,
            daily_drawdown_limit=Decimal(limit),
        )

    def test_single_large_loss_exceeding_limit_triggers_halt(self):
        guard = self._guard("100")
        guard.on_trade_result(Decimal("-150"))
        assert guard.state is GuardState.HALTED

    def test_multiple_small_losses_accumulate_and_trigger_halt(self):
        guard = self._guard("100")
        for _ in range(5):
            guard.on_trade_result(Decimal("-25"))  # cumulative = -125 after 5th
        assert guard.state is GuardState.HALTED

    def test_partial_recovery_keeps_active_when_cumulative_above_threshold(self):
        guard = self._guard("100")
        guard.on_trade_result(Decimal("-80"))   # cumulative = -80
        guard.on_trade_result(Decimal("30"))    # cumulative = -50
        guard.on_trade_result(Decimal("-40"))   # cumulative = -90
        assert guard.state is GuardState.ACTIVE
        assert guard.daily_pnl == Decimal("-90")


# ---------------------------------------------------------------------------
# CD4: Daily drawdown off-by-one — 3 tests, limit=Decimal("100")
# ---------------------------------------------------------------------------


class TestDailyDrawdownOffByOne:
    """Boundary: cumulative <= -100 triggers (equality included)."""

    LIMIT = Decimal("100")

    def _guard(self) -> RiskGuard:
        return RiskGuard(
            consecutive_loss_limit=99,
            on_halt=lambda: None,
            daily_drawdown_limit=self.LIMIT,
        )

    def test_cumulative_minus_99_99_does_not_halt(self):
        guard = self._guard()
        guard.on_trade_result(Decimal("-99.99"))
        assert guard.state is GuardState.ACTIVE

    def test_cumulative_exactly_minus_100_halts(self):
        guard = self._guard()
        guard.on_trade_result(Decimal("-100"))
        assert guard.state is GuardState.HALTED

    def test_cumulative_minus_100_01_halts(self):
        guard = self._guard()
        guard.on_trade_result(Decimal("-100.01"))
        assert guard.state is GuardState.HALTED


# ---------------------------------------------------------------------------
# CD5: reset_daily — 3 tests
# ---------------------------------------------------------------------------


class TestResetDaily:
    def _guard(self, limit: str = "100") -> RiskGuard:
        return RiskGuard(
            consecutive_loss_limit=99,
            on_halt=lambda: None,
            daily_drawdown_limit=Decimal(limit),
        )

    def test_reset_daily_clears_accumulated_pnl_and_state_stays_active(self):
        guard = self._guard("100")
        guard.on_trade_result(Decimal("-90"))  # near limit, not triggered
        assert guard.state is GuardState.ACTIVE
        guard.reset_daily()
        assert guard.daily_pnl == Decimal(0)
        assert guard.state is GuardState.ACTIVE

    def test_after_reset_accumulation_restarts_from_zero(self):
        guard = self._guard("100")
        guard.on_trade_result(Decimal("-90"))
        guard.reset_daily()
        # After reset, 90 more loss should not trigger (below limit again)
        guard.on_trade_result(Decimal("-90"))
        assert guard.state is GuardState.ACTIVE
        assert guard.daily_pnl == Decimal("-90")

    def test_reset_daily_does_not_clear_halted_state(self):
        guard = self._guard("100")
        guard.on_trade_result(Decimal("-100"))  # drawdown halt
        assert guard.state is GuardState.HALTED
        guard.reset_daily()
        assert guard.daily_pnl == Decimal(0)
        assert guard.state is GuardState.HALTED  # HALTED persists


# ---------------------------------------------------------------------------
# CD6: Daily halt callback spy — 2 tests
# ---------------------------------------------------------------------------


class TestDailyHaltCallback:
    def test_drawdown_halt_calls_on_halt_exactly_once(self):
        callback = MagicMock()
        guard = RiskGuard(
            consecutive_loss_limit=99,
            on_halt=callback,
            daily_drawdown_limit=Decimal("100"),
        )
        guard.on_trade_result(Decimal("-100"))
        callback.assert_called_once()

    def test_no_repeated_callback_after_drawdown_halt(self):
        callback = MagicMock()
        guard = RiskGuard(
            consecutive_loss_limit=99,
            on_halt=callback,
            daily_drawdown_limit=Decimal("100"),
        )
        guard.on_trade_result(Decimal("-100"))
        assert callback.call_count == 1
        guard.on_trade_result(Decimal("-50"))
        guard.on_trade_result(Decimal("-50"))
        assert callback.call_count == 1


# ---------------------------------------------------------------------------
# CD7: Dual halt paths are independent — 2 tests
# ---------------------------------------------------------------------------


class TestDualHaltPaths:
    def test_drawdown_triggers_halt_without_consecutive_loss_limit_reached(self):
        # consecutive_loss_limit=10, so 3 losses never hit it; drawdown=50 does
        guard = RiskGuard(
            consecutive_loss_limit=10,
            on_halt=lambda: None,
            daily_drawdown_limit=Decimal("50"),
        )
        guard.on_trade_result(Decimal("-20"))
        guard.on_trade_result(Decimal("-20"))
        guard.on_trade_result(Decimal("-20"))  # cumulative=-60, drawdown triggers
        assert guard.state is GuardState.HALTED
        assert guard.consecutive_losses < 10

    def test_consecutive_loss_triggers_halt_without_drawdown_limit_reached(self):
        # drawdown_limit=10000, so 3 losses of -1 never hit it; consecutive_loss_limit=3 does
        guard = RiskGuard(
            consecutive_loss_limit=3,
            on_halt=lambda: None,
            daily_drawdown_limit=Decimal("10000"),
        )
        guard.on_trade_result(Decimal("-1"))
        guard.on_trade_result(Decimal("-1"))
        guard.on_trade_result(Decimal("-1"))  # 3rd consecutive loss triggers
        assert guard.state is GuardState.HALTED
        assert guard.daily_pnl > -Decimal("10000")


# ---------------------------------------------------------------------------
# CD8: check_order gate after drawdown halt — 2 tests
# ---------------------------------------------------------------------------


class TestCheckOrderAfterDrawdown:
    def test_drawdown_halt_blocks_check_order(self):
        guard = RiskGuard(
            consecutive_loss_limit=99,
            on_halt=lambda: None,
            daily_drawdown_limit=Decimal("100"),
        )
        guard.on_trade_result(Decimal("-100"))
        with pytest.raises(RiskDenied):
            guard.check_order()

    def test_active_with_drawdown_limit_set_allows_check_order(self):
        guard = RiskGuard(
            consecutive_loss_limit=99,
            on_halt=lambda: None,
            daily_drawdown_limit=Decimal("100"),
        )
        guard.on_trade_result(Decimal("-50"))  # below limit
        guard.check_order()  # must not raise


# ---------------------------------------------------------------------------
# CN3: Notional cap threshold semantics — below / equal / above cap
# ---------------------------------------------------------------------------


class TestNotionalCapThreshold:
    CAP = Decimal("500")

    def _guard(self, cap: Decimal = CAP) -> RiskGuard:
        return RiskGuard(
            consecutive_loss_limit=99,
            on_halt=lambda: None,
            max_order_notional=cap,
        )

    def test_notional_below_cap_passes(self):
        self._guard().check_order(notional=Decimal("499.99"))

    def test_notional_equal_cap_passes(self):
        self._guard().check_order(notional=Decimal("500"))

    def test_notional_above_cap_raises(self):
        with pytest.raises(RiskDenied):
            self._guard().check_order(notional=Decimal("500.01"))


# ---------------------------------------------------------------------------
# CN4: Notional cap off-by-one — cap=100
# ---------------------------------------------------------------------------


class TestNotionalCapOffByOne:
    def _guard(self) -> RiskGuard:
        return RiskGuard(
            consecutive_loss_limit=99,
            on_halt=lambda: None,
            max_order_notional=Decimal("100"),
        )

    def test_99_99_passes(self):
        self._guard().check_order(notional=Decimal("99.99"))

    def test_100_00_passes(self):
        self._guard().check_order(notional=Decimal("100.00"))

    def test_100_01_raises(self):
        with pytest.raises(RiskDenied):
            self._guard().check_order(notional=Decimal("100.01"))


# ---------------------------------------------------------------------------
# CN5: Backward compatibility — None notional / None cap / legacy no-arg call
# ---------------------------------------------------------------------------


class TestNotionalCapBackwardCompat:
    def test_no_notional_arg_no_cap_passes(self):
        guard = RiskGuard(consecutive_loss_limit=3, on_halt=lambda: None)
        guard.check_order()

    def test_notional_passed_but_no_cap_set_passes(self):
        guard = RiskGuard(consecutive_loss_limit=3, on_halt=lambda: None)
        guard.check_order(notional=Decimal("999999"))

    def test_cap_set_but_no_notional_arg_passes(self):
        guard = RiskGuard(
            consecutive_loss_limit=3,
            on_halt=lambda: None,
            max_order_notional=Decimal("100"),
        )
        guard.check_order()


# ---------------------------------------------------------------------------
# CN6: Exceeding cap raises RiskDenied (not bare assert, not new type)
# ---------------------------------------------------------------------------


class TestNotionalCapRaisesRiskDenied:
    def test_raises_risk_denied_with_readable_reason(self):
        guard = RiskGuard(
            consecutive_loss_limit=3,
            on_halt=lambda: None,
            max_order_notional=Decimal("100"),
        )
        with pytest.raises(RiskDenied) as exc_info:
            guard.check_order(notional=Decimal("100.01"))
        assert exc_info.value.reason
        assert isinstance(exc_info.value, RiskDenied)


# ---------------------------------------------------------------------------
# CN7: HALTED × notional — HALTED wins (D4=A)
# ---------------------------------------------------------------------------


class TestNotionalCapHaltedInteraction:
    def _guard(self) -> RiskGuard:
        return RiskGuard(
            consecutive_loss_limit=99,
            on_halt=lambda: None,
            max_order_notional=Decimal("100"),
        )

    def test_halted_and_notional_under_cap_raises_halted_reason(self):
        guard = self._guard()
        guard.halt()
        with pytest.raises(RiskDenied) as exc_info:
            guard.check_order(notional=Decimal("50"))
        assert "HALTED" in exc_info.value.reason

    def test_halted_and_notional_over_cap_raises_halted_reason(self):
        guard = self._guard()
        guard.halt()
        with pytest.raises(RiskDenied) as exc_info:
            guard.check_order(notional=Decimal("200"))
        assert "HALTED" in exc_info.value.reason

    def test_active_and_notional_over_cap_raises_notional_reason_not_halted(self):
        guard = self._guard()
        with pytest.raises(RiskDenied) as exc_info:
            guard.check_order(notional=Decimal("200"))
        assert "HALTED" not in exc_info.value.reason


# ---------------------------------------------------------------------------
# CN8: Decimal full path — high-precision Decimal comparisons stay exact
# ---------------------------------------------------------------------------


class TestNotionalCapDecimalPrecision:
    def test_high_precision_decimal_under_cap_passes(self):
        guard = RiskGuard(
            consecutive_loss_limit=3,
            on_halt=lambda: None,
            max_order_notional=Decimal("1000"),
        )
        guard.check_order(notional=Decimal("999.9999999999"))

    def test_high_precision_decimal_over_cap_raises(self):
        guard = RiskGuard(
            consecutive_loss_limit=3,
            on_halt=lambda: None,
            max_order_notional=Decimal("1000"),
        )
        with pytest.raises(RiskDenied):
            guard.check_order(notional=Decimal("1000.0000000001"))
