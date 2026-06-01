"""Tests for ExecReconciler — CR12 T1~T4."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from hermes.execution.exec_reconciler import ExecReconciler


class TestExecReconciler:
    def test_t1_calls_reconcile_with_configured_timeout(self):
        engine = MagicMock()
        engine.reconcile_execution_state = AsyncMock(return_value=True)
        reconciler = ExecReconciler(exec_engine=engine, timeout_secs=7.5)

        import asyncio
        asyncio.get_event_loop().run_until_complete(reconciler.kickoff())

        engine.reconcile_execution_state.assert_called_once_with(timeout_secs=7.5)

    def test_t2_true_result_does_not_invoke_on_failure(self):
        engine = MagicMock()
        engine.reconcile_execution_state = AsyncMock(return_value=True)
        on_failure = MagicMock()
        reconciler = ExecReconciler(exec_engine=engine, on_failure=on_failure)

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(reconciler.kickoff())

        assert result is True
        on_failure.assert_not_called()

    def test_t3_false_result_invokes_on_failure_once_with_reason(self):
        engine = MagicMock()
        engine.reconcile_execution_state = AsyncMock(return_value=False)
        on_failure = MagicMock()
        reconciler = ExecReconciler(exec_engine=engine, on_failure=on_failure)

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(reconciler.kickoff())

        assert result is False
        on_failure.assert_called_once()
        reason = on_failure.call_args[0][0]
        assert isinstance(reason, str) and len(reason) > 0

    def test_t4_source_contains_no_riskguard_reference(self):
        src = open("src/hermes/execution/exec_reconciler.py").read()
        assert "RiskGuard" not in src


# ── CE8: on_failure wired to risk_guard.halt() → HALTED, spy exactly 1 ───────

class TestCE8ReconcilerHaltsGuard:
    def test_kickoff_false_halts_risk_guard(self):
        """kickoff() returns False → on_failure called exactly once → RiskGuard HALTED."""
        from hermes.risk.guard import GuardState, RiskGuard

        engine = MagicMock()
        engine.reconcile_execution_state = AsyncMock(return_value=False)

        guard = RiskGuard(on_halt=MagicMock(), consecutive_loss_limit=3)
        on_failure_spy = MagicMock(side_effect=lambda msg: guard.halt())
        reconciler = ExecReconciler(
            exec_engine=engine,
            on_failure=on_failure_spy,
        )

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(reconciler.kickoff())

        assert result is False
        assert guard.state is GuardState.HALTED
        on_failure_spy.assert_called_once()

    def test_kickoff_true_guard_remains_active(self):
        """kickoff() returns True → on_failure not invoked → guard stays ACTIVE."""
        from hermes.risk.guard import GuardState, RiskGuard

        engine = MagicMock()
        engine.reconcile_execution_state = AsyncMock(return_value=True)

        guard = RiskGuard(on_halt=MagicMock(), consecutive_loss_limit=3)
        on_failure_spy = MagicMock(side_effect=lambda msg: guard.halt())
        reconciler = ExecReconciler(
            exec_engine=engine,
            on_failure=on_failure_spy,
        )

        import asyncio
        asyncio.get_event_loop().run_until_complete(reconciler.kickoff())
        assert guard.state is GuardState.ACTIVE
        on_failure_spy.assert_not_called()
