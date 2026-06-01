"""Tests for RiskGuard throttle gate — CBT1~CBT10."""

from __future__ import annotations

from decimal import Decimal

import pytest

from hermes.risk.guard import GuardState, RiskDenied, RiskGuard


# ---------------------------------------------------------------------------
# CBT3 — Window semantics: under max / at max / over max
# ---------------------------------------------------------------------------


class TestThrottleWindowSemantics:
    MAX = 3
    WIN = 10.0  # seconds

    def _guard(self) -> RiskGuard:
        return RiskGuard(
            consecutive_loss_limit=99,
            on_halt=lambda: None,
            max_orders_per_window=self.MAX,
            window_seconds=self.WIN,
        )

    def test_cbt3_under_max_passes(self):
        guard = self._guard()
        for i in range(self.MAX - 1):
            guard.check_order(now=float(i))  # 0, 1 — 2 calls, max=3

    def test_cbt3_at_max_this_call_passes(self):
        guard = self._guard()
        for i in range(self.MAX):  # 0, 1, 2 — exactly max calls
            guard.check_order(now=float(i))

    def test_cbt3_over_max_raises(self):
        guard = self._guard()
        for i in range(self.MAX):
            guard.check_order(now=float(i))
        with pytest.raises(RiskDenied):
            guard.check_order(now=float(self.MAX))


# ---------------------------------------------------------------------------
# CBT4 — Sliding window expiry: old timestamps pruned, quota restored
# ---------------------------------------------------------------------------


class TestThrottleSlidingWindowExpiry:
    def test_cbt4_expired_timestamps_pruned(self):
        guard = RiskGuard(
            consecutive_loss_limit=99,
            on_halt=lambda: None,
            max_orders_per_window=2,
            window_seconds=5.0,
        )
        # Fill window at t=0 and t=1
        guard.check_order(now=0.0)
        guard.check_order(now=1.0)
        # At t=6, both timestamps (0 and 1) are outside (6-5, 6] = (1, 6]
        # t=0: 0 <= 1 → expired; t=1: 1 <= 1 → expired (strictly > required)
        guard.check_order(now=6.0)  # both expired, window empty → passes

    def test_cbt4_boundary_timestamp_exactly_at_edge_is_pruned(self):
        guard = RiskGuard(
            consecutive_loss_limit=99,
            on_halt=lambda: None,
            max_orders_per_window=1,
            window_seconds=5.0,
        )
        guard.check_order(now=0.0)
        # t=5: window is (5-5, 5] = (0, 5]. t=0 is not strictly > 0 → pruned
        guard.check_order(now=5.0)  # t=0 expired → passes

    def test_cbt4_partial_expiry_keeps_recent(self):
        guard = RiskGuard(
            consecutive_loss_limit=99,
            on_halt=lambda: None,
            max_orders_per_window=2,
            window_seconds=5.0,
        )
        guard.check_order(now=0.0)  # will expire at t=5
        guard.check_order(now=3.0)  # will expire at t=8
        # At t=6: t=0 expired, t=3 still in window (3 > 6-5=1 ✓)
        # window has 1 entry, max=2 → passes and records t=6
        guard.check_order(now=6.0)
        # window now has t=3 and t=6 (2 entries = max) → next rejected
        with pytest.raises(RiskDenied):
            guard.check_order(now=6.5)


# ---------------------------------------------------------------------------
# CBT5 — Off-by-one (max=3): 3rd passes, 4th rejected
# ---------------------------------------------------------------------------


class TestThrottleOffByOne:
    def test_cbt5_third_passes(self):
        guard = RiskGuard(
            consecutive_loss_limit=99,
            on_halt=lambda: None,
            max_orders_per_window=3,
            window_seconds=60.0,
        )
        guard.check_order(now=1.0)
        guard.check_order(now=2.0)
        guard.check_order(now=3.0)  # 3rd = max → passes

    def test_cbt5_fourth_rejected(self):
        guard = RiskGuard(
            consecutive_loss_limit=99,
            on_halt=lambda: None,
            max_orders_per_window=3,
            window_seconds=60.0,
        )
        guard.check_order(now=1.0)
        guard.check_order(now=2.0)
        guard.check_order(now=3.0)
        with pytest.raises(RiskDenied):
            guard.check_order(now=4.0)  # 4th → rejected


# ---------------------------------------------------------------------------
# CBT6 — Backward compat: any throttle parameter None → skip throttle check
# ---------------------------------------------------------------------------


class TestThrottleBackwardCompat:
    def test_cbt6_all_none_passes(self):
        guard = RiskGuard(consecutive_loss_limit=3, on_halt=lambda: None)
        guard.check_order()  # no throttle params at all — must not raise

    def test_cbt6_now_none_but_params_set_passes(self):
        guard = RiskGuard(
            consecutive_loss_limit=3,
            on_halt=lambda: None,
            max_orders_per_window=1,
            window_seconds=60.0,
        )
        # now=None → throttle skipped even if max/window set
        guard.check_order()
        guard.check_order()  # second call, no throttle, still passes

    def test_cbt6_params_none_but_now_passed_passes(self):
        guard = RiskGuard(consecutive_loss_limit=3, on_halt=lambda: None)
        # max_orders_per_window and window_seconds not set → throttle skipped
        for _ in range(10):
            guard.check_order(now=1.0)  # must not raise

    def test_cbt6_window_seconds_none_skips_throttle(self):
        guard = RiskGuard(
            consecutive_loss_limit=3,
            on_halt=lambda: None,
            max_orders_per_window=1,
        )
        guard.check_order(now=1.0)
        guard.check_order(now=2.0)  # window_seconds=None → skip throttle


# ---------------------------------------------------------------------------
# CBT7 — Raises RiskDenied; reason contains throttle keyword
# ---------------------------------------------------------------------------


class TestThrottleRaisesRiskDenied:
    def test_cbt7_raises_risk_denied_with_throttle_reason(self):
        guard = RiskGuard(
            consecutive_loss_limit=99,
            on_halt=lambda: None,
            max_orders_per_window=1,
            window_seconds=60.0,
        )
        guard.check_order(now=1.0)
        with pytest.raises(RiskDenied) as exc_info:
            guard.check_order(now=2.0)
        assert isinstance(exc_info.value, RiskDenied)
        assert exc_info.value.reason
        assert "throttle" in exc_info.value.reason.lower() or "Throttle" in exc_info.value.reason


# ---------------------------------------------------------------------------
# CBT8 — Four-gate priority + D5: earlier-gate rejects don't consume quota
# ---------------------------------------------------------------------------


class TestFourGatePriorityAndD5:
    def _guard(self) -> RiskGuard:
        return RiskGuard(
            consecutive_loss_limit=99,
            on_halt=lambda: None,
            max_order_notional=Decimal("500"),
            min_balance=Decimal("100"),
            max_orders_per_window=2,
            window_seconds=60.0,
        )

    def test_cbt8_halted_wins_over_throttle(self):
        guard = self._guard()
        guard.halt()
        with pytest.raises(RiskDenied) as exc_info:
            guard.check_order(now=1.0)
        assert "HALTED" in exc_info.value.reason

    def test_cbt8_notional_gate_before_throttle(self):
        guard = self._guard()
        with pytest.raises(RiskDenied) as exc_info:
            guard.check_order(notional=Decimal("600"), now=1.0)
        assert "throttle" not in exc_info.value.reason.lower()
        assert "HALTED" not in exc_info.value.reason

    def test_cbt8_balance_gate_before_throttle(self):
        guard = self._guard()
        with pytest.raises(RiskDenied) as exc_info:
            guard.check_order(balance=Decimal("50"), now=1.0)
        assert "balance" in exc_info.value.reason.lower()
        assert "throttle" not in exc_info.value.reason.lower()

    def test_cbt8_d5_rejected_by_balance_does_not_consume_quota(self):
        guard = self._guard()
        # Exhaust quota via valid calls
        guard.check_order(now=1.0)
        guard.check_order(now=2.0)
        # Two balance-rejected calls — must NOT consume throttle quota
        for _ in range(5):
            with pytest.raises(RiskDenied):
                guard.check_order(balance=Decimal("50"), now=3.0)
        # After 5 balance-rejected calls, throttle window still has only 2 stamps
        # → next valid call (without balance) should be rejected by throttle, not pass
        with pytest.raises(RiskDenied) as exc_info:
            guard.check_order(now=4.0)
        assert "throttle" in exc_info.value.reason.lower() or "Throttle" in exc_info.value.reason

    def test_cbt8_d5_rejected_by_notional_does_not_consume_quota(self):
        guard = self._guard()
        # Notional-rejected calls should not consume quota
        for _ in range(5):
            with pytest.raises(RiskDenied):
                guard.check_order(notional=Decimal("600"), now=1.0)
        # Throttle window still empty → valid call passes
        guard.check_order(now=2.0)


# ---------------------------------------------------------------------------
# CBT1 / CBT2 — Zero-dependency + docstring checks (static)
# ---------------------------------------------------------------------------


class TestDocstringAndDependencies:
    def test_cbt1_no_time_import_in_guard(self):
        import inspect

        import hermes.risk.guard as mod

        src = inspect.getsource(mod)
        assert "import time" not in src
        assert "time.monotonic" not in src
        assert "time.time" not in src
        assert "datetime" not in src

    def test_cbt1_no_nautilus_import_in_guard(self):
        import inspect

        import hermes.risk.guard as mod

        src = inspect.getsource(mod)
        assert "import nautilus" not in src
        assert "from nautilus" not in src

    def test_cbt1_no_float_call_in_guard(self):
        import inspect

        import hermes.risk.guard as mod

        src = inspect.getsource(mod)
        assert "float(" not in src

    def test_cbt2_frequency_throttle_not_in_out_of_scope(self):
        from hermes.risk.guard import RiskGuard as RG

        doc = RG.__doc__ or ""
        oos_idx = doc.find("Out of scope")
        assert oos_idx >= 0
        oos_tail = doc[oos_idx:]
        assert "frequency/throttle" not in oos_tail

    def test_cbt2_price_quantity_precision_still_in_out_of_scope(self):
        from hermes.risk.guard import RiskGuard as RG

        doc = RG.__doc__ or ""
        oos_idx = doc.find("Out of scope")
        assert "price/quantity precision" in doc[oos_idx:]

    def test_cbt2_responsibilities_mentions_throttle(self):
        from hermes.risk.guard import RiskGuard as RG

        doc = RG.__doc__ or ""
        assert "throttle" in doc.lower()
        assert "four-gate" in doc.lower() or "fourth" in doc.lower()

    def test_cbt2_lc_risk3_documented(self):
        from hermes.risk.guard import RiskGuard as RG

        doc = RG.__doc__ or ""
        assert "LC-RISK-3" in doc
