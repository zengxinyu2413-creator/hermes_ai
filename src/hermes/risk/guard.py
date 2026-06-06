"""RiskGuard: pure-logic killswitch + consecutive-loss circuit breaker."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Callable

from hermes.core.exceptions import HermesError
from hermes.risk.risk_state_store import RiskStateStore


class GuardState(Enum):
    ACTIVE = "ACTIVE"
    HALTED = "HALTED"


class RiskDenied(HermesError):
    """Raised when RiskGuard blocks an order due to HALTED state or risk limit breach."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class RiskGuard:
    """Killswitch + consecutive-loss circuit breaker + daily drawdown guard.

    Responsibilities:
    - State machine: ACTIVE → HALTED (one-way via halt() or N consecutive losses).
    - check_order: raises RiskDenied when HALTED; also enforces max_order_notional
      cap (notional > cap → RiskDenied) when both notional and max_order_notional
      are provided; also enforces min_balance floor (balance < floor → RiskDenied)
      when both balance and min_balance are provided; also enforces throttle
      (window count >= max → RiskDenied) when now, max_orders_per_window, and
      window_seconds are all provided. Four-gate priority: HALTED first, notional
      cap second, balance floor third, throttle fourth.
    - on_trade_result: increments loss counter on pnl < 0; resets on pnl >= 0.
      Also accumulates daily PnL; halts when cumulative <= -daily_drawdown_limit.
    - reset_daily: resets daily PnL accumulator to zero (does not clear HALTED).
    - state_store: optional RiskStateStore injection for cross-restart persistence
      of consecutive_losses and HALTED state. store=None = current in-memory
      behaviour (byte-level identical, D1). HALTED persists across restarts —
      the single-direction safety lock cannot be cleared by restart alone (D5).

    Symbol convention for daily_drawdown_limit: a positive Decimal representing the
    maximum tolerated intraday loss in absolute terms. Halt triggers when
    cumulative daily PnL <= -daily_drawdown_limit (loss >= limit; equality included).

    max_order_notional: a positive Decimal cap per order in notional terms.
    Notional above cap (notional > max_order_notional) → RiskDenied.
    Notional equal to cap is allowed (cap is inclusive upper bound).

    min_balance: a positive Decimal floor for post-trade available balance.
    Balance below floor (balance < min_balance) → RiskDenied.
    Balance equal to floor is allowed (floor is inclusive lower bound).

    max_orders_per_window / window_seconds: sliding-window throttle. guard never
    calls time.*; the caller supplies now (epoch or monotonic seconds, consistent
    within a session). LC-RISK-3: throttle window (_order_times) is in-memory
    only and lost on process restart — not persisted via RiskStateStore.

    Out of scope (by design — handled by NT RiskEngine or later phases):
    price/quantity precision.
    """

    def __init__(
        self,
        consecutive_loss_limit: int,
        on_halt: Callable[[], None],
        daily_drawdown_limit: Decimal | None = None,
        max_order_notional: Decimal | None = None,
        state_store: RiskStateStore | None = None,
        min_balance: Decimal | None = None,
        max_orders_per_window: int | None = None,
        window_seconds: float | None = None,
        now: float | None = None,
    ) -> None:
        self._limit = consecutive_loss_limit
        self._on_halt = on_halt
        self._daily_drawdown_limit = daily_drawdown_limit
        self._max_order_notional = max_order_notional
        self._min_balance = min_balance
        self._max_orders_per_window = max_orders_per_window
        self._window_seconds = window_seconds
        self._store = state_store
        self._state = GuardState.ACTIVE
        self._consecutive_losses: int = 0
        self._daily_pnl: Decimal = Decimal(0)
        self._order_times: list[float] = []
        if state_store is not None:
            snap = state_store.load()
            if snap is not None:
                self._state = GuardState(snap["state"])
                self._consecutive_losses = snap["consecutive_losses"]
                if now is not None and "daily_pnl_date" in snap:
                    today = datetime.fromtimestamp(now, tz=timezone.utc).date().isoformat()
                    if snap["daily_pnl_date"] == today:
                        self._daily_pnl = Decimal(snap["daily_pnl"])

    def _snapshot(self, now: float | None = None) -> dict:
        snap: dict = {"state": self._state.value, "consecutive_losses": self._consecutive_losses}
        if now is not None:
            snap["daily_pnl"] = str(self._daily_pnl)
            snap["daily_pnl_date"] = datetime.fromtimestamp(now, tz=timezone.utc).date().isoformat()
        return snap

    @property
    def state(self) -> GuardState:
        return self._state

    @property
    def consecutive_losses(self) -> int:
        return self._consecutive_losses

    @property
    def daily_pnl(self) -> Decimal:
        return self._daily_pnl

    def halt(self) -> None:
        """Trip the killswitch to HALTED (idempotent)."""
        self._state = GuardState.HALTED
        if self._store is not None:
            self._store.save(self._snapshot())

    def check_order(
        self,
        notional: Decimal | None = None,
        balance: Decimal | None = None,
        now: float | None = None,
    ) -> None:
        """Raise RiskDenied if any of the four gates is breached.

        Four-gate priority: HALTED first; notional cap second; balance floor
        third; throttle fourth. Each gate raises immediately; subsequent gates
        are skipped. Throttle quota is only recorded after all four gates pass
        (D5: calls rejected by an earlier gate do not consume throttle quota).

        Notional cap: enforced when both notional and max_order_notional are set,
        and notional > max_order_notional. Equal to cap is allowed (inclusive).

        Balance floor: enforced when both balance and min_balance are set, and
        balance < min_balance. Equal to floor is allowed (inclusive lower bound).
        balance is the post-trade expected available balance supplied by the
        caller; guard does not infer the balance impact of the order.

        Throttle: enforced when now, max_orders_per_window, and window_seconds
        are all set. Sliding window retains timestamps strictly inside
        (now - window_seconds, now]; window count >= max → RiskDenied. now is
        supplied by the caller; guard never calls time.* (LC-RISK-3).
        """
        if self._state is GuardState.HALTED:
            raise RiskDenied("RiskGuard is HALTED; order rejected")
        if notional is not None and self._max_order_notional is not None:
            if notional > self._max_order_notional:
                raise RiskDenied(
                    f"Order notional {notional} exceeds cap {self._max_order_notional}"
                )
        if balance is not None and self._min_balance is not None:
            if balance < self._min_balance:
                raise RiskDenied(
                    f"Post-trade balance {balance} below floor {self._min_balance}"
                )
        if (
            now is not None
            and self._max_orders_per_window is not None
            and self._window_seconds is not None
        ):
            self._order_times = [t for t in self._order_times if t > now - self._window_seconds]
            if len(self._order_times) >= self._max_orders_per_window:
                raise RiskDenied(
                    f"Throttle: {self._max_orders_per_window} orders per"
                    f" {self._window_seconds}s window exceeded"
                )
            self._order_times.append(now)

    def on_trade_result(self, pnl: Decimal, now: float | None = None) -> None:
        """Feed a completed trade's PnL. pnl < 0 counts as a loss.

        now: epoch seconds (UTC). When provided, persists daily_pnl + date so
        cross-restart restore works (B1 opt-in). When None, daily_pnl is not
        included in the snapshot (backward-compatible, D2 boundary preserved).
        """
        if self._state is GuardState.HALTED:
            return
        self._daily_pnl += pnl
        if (
            self._daily_drawdown_limit is not None
            and self._daily_pnl <= -self._daily_drawdown_limit
        ):
            self._state = GuardState.HALTED
            self._on_halt()
            if self._store is not None:
                self._store.save(self._snapshot(now))
            return
        if pnl < Decimal(0):
            self._consecutive_losses += 1
            if self._consecutive_losses >= self._limit:
                self._state = GuardState.HALTED
                self._on_halt()
            if self._store is not None:
                self._store.save(self._snapshot(now))
        else:
            self._consecutive_losses = 0
            if self._store is not None:
                self._store.save(self._snapshot(now))

    def reset_daily(self, now: float | None = None) -> None:
        """Reset the daily PnL accumulator to zero. Does not clear HALTED state.

        now: epoch seconds. When provided and store is set, persists the zeroed
        accumulator with today's date so the next restart sees a clean slate.
        """
        self._daily_pnl = Decimal(0)
        if now is not None and self._store is not None:
            self._store.save(self._snapshot(now))
