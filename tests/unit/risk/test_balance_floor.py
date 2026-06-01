"""Tests for RiskGuard balance floor gate — CBF1~CBF10."""

from __future__ import annotations

from decimal import Decimal

import pytest

from hermes.risk.guard import GuardState, RiskDenied, RiskGuard


# ---------------------------------------------------------------------------
# CBF3 — Threshold semantics (floor=100): above / equal / below
# ---------------------------------------------------------------------------


class TestBalanceFloorThreshold:
    FLOOR = Decimal("100")

    def _guard(self, floor: Decimal = FLOOR) -> RiskGuard:
        return RiskGuard(consecutive_loss_limit=99, on_halt=lambda: None, min_balance=floor)

    def test_cbf3_balance_above_floor_passes(self):
        self._guard().check_order(balance=Decimal("100.01"))

    def test_cbf3_balance_equal_floor_passes(self):
        self._guard().check_order(balance=Decimal("100.00"))

    def test_cbf3_balance_below_floor_raises(self):
        with pytest.raises(RiskDenied):
            self._guard().check_order(balance=Decimal("99.99"))


# ---------------------------------------------------------------------------
# CBF4 — Off-by-one (floor=50): inclusive lower bound nailed
# ---------------------------------------------------------------------------


class TestBalanceFloorOffByOne:
    FLOOR = Decimal("50")

    def _guard(self) -> RiskGuard:
        return RiskGuard(
            consecutive_loss_limit=99, on_halt=lambda: None, min_balance=self.FLOOR
        )

    def test_cbf4_50_01_passes(self):
        self._guard().check_order(balance=Decimal("50.01"))

    def test_cbf4_50_00_passes_inclusive_bound(self):
        self._guard().check_order(balance=Decimal("50.00"))

    def test_cbf4_49_99_raises(self):
        with pytest.raises(RiskDenied):
            self._guard().check_order(balance=Decimal("49.99"))


# ---------------------------------------------------------------------------
# CBF5 — Backward compat: any None in the pair → floor check skipped
# ---------------------------------------------------------------------------


class TestBalanceFloorBackwardCompat:
    def test_cbf5_min_balance_none_balance_provided_passes(self):
        guard = RiskGuard(consecutive_loss_limit=3, on_halt=lambda: None)
        guard.check_order(balance=Decimal("0.01"))  # no floor set — must not raise

    def test_cbf5_min_balance_set_balance_none_passes(self):
        guard = RiskGuard(
            consecutive_loss_limit=3, on_halt=lambda: None, min_balance=Decimal("100")
        )
        guard.check_order()  # balance not supplied — must not raise

    def test_cbf5_both_none_passes(self):
        guard = RiskGuard(consecutive_loss_limit=3, on_halt=lambda: None)
        guard.check_order()  # legacy no-arg call — must not raise


# ---------------------------------------------------------------------------
# CBF6 — Raises RiskDenied (not bare assert, not new type); reason contains "balance"
# ---------------------------------------------------------------------------


class TestBalanceFloorRaisesRiskDenied:
    def test_cbf6_raises_risk_denied_instance(self):
        guard = RiskGuard(
            consecutive_loss_limit=3, on_halt=lambda: None, min_balance=Decimal("100")
        )
        with pytest.raises(RiskDenied) as exc_info:
            guard.check_order(balance=Decimal("50"))
        assert isinstance(exc_info.value, RiskDenied)
        assert exc_info.value.reason
        assert "balance" in exc_info.value.reason.lower()


# ---------------------------------------------------------------------------
# CBF7 — Three-gate priority (D4): HALTED > notional > balance (4 tests)
# ---------------------------------------------------------------------------


class TestThreeGatePriority:
    NOTIONAL_CAP = Decimal("500")
    BALANCE_FLOOR = Decimal("100")

    def _guard(self) -> RiskGuard:
        return RiskGuard(
            consecutive_loss_limit=99,
            on_halt=lambda: None,
            max_order_notional=self.NOTIONAL_CAP,
            min_balance=self.BALANCE_FLOOR,
        )

    def test_cbf7_halted_adequate_balance_halted_reason(self):
        guard = self._guard()
        guard.halt()
        with pytest.raises(RiskDenied) as exc_info:
            guard.check_order(notional=Decimal("100"), balance=Decimal("999"))
        assert "HALTED" in exc_info.value.reason

    def test_cbf7_active_notional_over_cap_adequate_balance_notional_reason(self):
        guard = self._guard()
        with pytest.raises(RiskDenied) as exc_info:
            guard.check_order(notional=Decimal("600"), balance=Decimal("999"))
        assert "HALTED" not in exc_info.value.reason
        assert "balance" not in exc_info.value.reason.lower()

    def test_cbf7_active_notional_ok_balance_below_floor_balance_reason(self):
        guard = self._guard()
        with pytest.raises(RiskDenied) as exc_info:
            guard.check_order(notional=Decimal("100"), balance=Decimal("50"))
        assert "balance" in exc_info.value.reason.lower()
        assert "HALTED" not in exc_info.value.reason

    def test_cbf7_active_notional_over_cap_balance_below_floor_notional_wins(self):
        guard = self._guard()
        with pytest.raises(RiskDenied) as exc_info:
            guard.check_order(notional=Decimal("600"), balance=Decimal("50"))
        # notional gate fires first — reason must NOT reference balance
        assert "balance" not in exc_info.value.reason.lower()
        assert "HALTED" not in exc_info.value.reason


# ---------------------------------------------------------------------------
# CBF8 — Decimal full path: no float(, high-precision comparisons exact
# ---------------------------------------------------------------------------


class TestBalanceFloorDecimalPrecision:
    FLOOR = Decimal("100")

    def _guard(self) -> RiskGuard:
        return RiskGuard(
            consecutive_loss_limit=3, on_halt=lambda: None, min_balance=self.FLOOR
        )

    def test_cbf8_high_precision_above_floor_passes(self):
        self._guard().check_order(balance=Decimal("100.0000000001"))

    def test_cbf8_high_precision_below_floor_raises(self):
        with pytest.raises(RiskDenied):
            self._guard().check_order(balance=Decimal("99.9999999999"))


# ---------------------------------------------------------------------------
# CBF1 / CBF2 — Docstring + zero-dependency checks (static)
# ---------------------------------------------------------------------------


class TestDocstringAndDependencies:
    def test_cbf2_balance_removed_from_out_of_scope(self):
        from hermes.risk.guard import RiskGuard as RG

        doc = RG.__doc__ or ""
        oos_idx = doc.find("Out of scope")
        assert oos_idx >= 0
        oos_tail = doc[oos_idx:]
        # balance is now in-scope (§2.23); must NOT appear in out-of-scope tail
        assert "balance" not in oos_tail
        # balance should appear in Responsibilities section
        assert "balance" in doc[:oos_idx].lower() or "min_balance" in doc[:oos_idx]

    def test_cbf2_price_quantity_precision_still_in_out_of_scope(self):
        # frequency/throttle moved in-scope at §2.24 (CBT slice); only
        # price/quantity precision remains out-of-scope after that slice.
        from hermes.risk.guard import RiskGuard as RG

        doc = RG.__doc__ or ""
        oos_idx = doc.find("Out of scope")
        oos_tail = doc[oos_idx:]
        assert "price/quantity precision" in oos_tail

    def test_cbf2_responsibilities_mentions_balance_floor(self):
        from hermes.risk.guard import RiskGuard as RG

        doc = RG.__doc__ or ""
        assert "min_balance" in doc or "balance floor" in doc.lower()

    def test_cbf1_no_nautilus_import_in_guard(self):
        import ast
        import inspect

        import hermes.risk.guard as mod

        src = inspect.getsource(mod)
        assert "import nautilus" not in src
        assert "from nautilus" not in src

    def test_cbf1_no_float_call_in_guard(self):
        import inspect

        import hermes.risk.guard as mod

        src = inspect.getsource(mod)
        assert "float(" not in src
