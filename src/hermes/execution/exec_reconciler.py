"""ExecReconciler: one-shot execution state reconciliation on startup."""

from __future__ import annotations

import logging
from typing import Callable, Optional


class ExecReconciler:
    """
    Triggers NT execution state reconciliation on startup.

    In scope: calling ExecEngine.reconcile_execution_state once at startup,
    invoking a configurable on_failure callback (exactly once) when reconciliation
    times out.

    Out of scope: HALT auto-trip on failure, retry strategy, partial reconciliation.
    """

    def __init__(
        self,
        exec_engine,
        timeout_secs: float = 10.0,
        on_failure: Optional[Callable[[str], None]] = None,
        logger=None,
    ) -> None:
        self._exec_engine = exec_engine
        self._timeout_secs = timeout_secs
        self._on_failure = on_failure
        self._log = logger if logger is not None else logging.getLogger(__name__)

    async def kickoff(self) -> bool:
        """Reconcile execution state; returns True on success, False on timeout."""
        result = await self._exec_engine.reconcile_execution_state(
            timeout_secs=self._timeout_secs
        )
        if result is False and self._on_failure is not None:
            self._on_failure("reconcile_timeout")
        return result
