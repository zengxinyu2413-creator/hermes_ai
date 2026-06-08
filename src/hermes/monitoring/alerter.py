"""Alerter — poll loop with debounced alerts and read-only command support.

Detects: connectivity loss, clock drift, price moves.
All Telegram sends are injected via send_fn to keep this module
free of python-telegram-bot imports (testable without the optional dep).
"""
from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal

from hermes.monitoring.rest_reader import RestReader

_PING_FAIL_THRESHOLD = 3


@dataclass(frozen=True)
class AlertSnapshot:
    ping_ok: bool
    server_time_ms: int | None
    latest_price: Decimal | None
    ts: float


class Alerter:
    """Poll Binance read endpoints and push Telegram alerts on anomalies."""

    def __init__(
        self,
        *,
        reader: RestReader,
        send_fn: Callable[[str], Awaitable[None]],
        poll_interval_s: int = 30,
        clock_drift_warn_ms: int = 1000,
        price_move_warn_pct: Decimal = Decimal("5.0"),
    ) -> None:
        self._reader = reader
        self._send = send_fn
        self._poll_interval_s = poll_interval_s
        self._clock_drift_warn_ms = clock_drift_warn_ms
        self._price_move_warn_pct = price_move_warn_pct

        self._last: AlertSnapshot | None = None
        self._ping_fail_count: int = 0
        self._alerted_ping: bool = False
        self._alerted_drift: bool = False
        self._alerted_price: bool = False
        self._stop_event: asyncio.Event | None = None

    @property
    def last_snapshot(self) -> AlertSnapshot | None:
        return self._last

    def get_status(self) -> str:
        """One-line status summary for the /status command."""
        if self._last is None:
            return "No data yet."
        snap = self._last
        price_str = f"{snap.latest_price:.2f}" if snap.latest_price is not None else "N/A"
        if snap.server_time_ms is not None:
            drift_ms = abs(snap.server_time_ms - int(time.time() * 1000))
            drift_str = f"{drift_ms}ms"
        else:
            drift_str = "N/A"
        ping_icon = "✅" if snap.ping_ok else "\U0001f534"
        return f"ping={ping_icon} price={price_str} drift={drift_str}"

    async def poll_once(self) -> None:
        """One poll cycle: check ping, drift, price. Public for testing."""
        ping_ok = await self._reader.read_ping()
        server_ms = await self._reader.read_server_time()
        klines = await self._reader.read_klines()

        now_local_ms = int(time.time() * 1000)

        # --- ping debounce ---
        if ping_ok:
            self._ping_fail_count = 0
            if self._alerted_ping:
                await self._send("✅ Binance REST reachable again.")
                self._alerted_ping = False
        else:
            self._ping_fail_count += 1
            if self._ping_fail_count >= _PING_FAIL_THRESHOLD and not self._alerted_ping:
                await self._send(
                    f"\U0001f534 Binance REST unreachable "
                    f"({self._ping_fail_count} consecutive failures)."
                )
                self._alerted_ping = True

        # --- clock drift debounce ---
        if server_ms is not None:
            drift_ms = abs(server_ms - now_local_ms)
            if drift_ms > self._clock_drift_warn_ms and not self._alerted_drift:
                await self._send(
                    f"⚠️ Clock drift {drift_ms}ms "
                    f"exceeds {self._clock_drift_warn_ms}ms threshold."
                )
                self._alerted_drift = True
            elif drift_ms <= self._clock_drift_warn_ms and self._alerted_drift:
                await self._send(f"✅ Clock drift recovered ({drift_ms}ms).")
                self._alerted_drift = False

        # --- price move debounce ---
        latest_price: Decimal | None = None
        if klines:
            with contextlib.suppress(Exception):
                latest_price = klines[-1].close

        if (
            latest_price is not None
            and self._last is not None
            and self._last.latest_price is not None
        ):
            prev = self._last.latest_price
            if prev > 0:
                change_pct = abs(latest_price - prev) / prev * Decimal(100)
                if change_pct > self._price_move_warn_pct and not self._alerted_price:
                    await self._send(
                        f"\U0001f4ca Price moved {change_pct:.2f}% "
                        f"({prev:.2f} → {latest_price:.2f})."
                    )
                    self._alerted_price = True
                elif change_pct <= self._price_move_warn_pct and self._alerted_price:
                    self._alerted_price = False

        self._last = AlertSnapshot(
            ping_ok=ping_ok,
            server_time_ms=server_ms,
            latest_price=latest_price,
            ts=time.time(),
        )

    async def run(self) -> None:
        """Poll loop. Exits when stop() is called."""
        self._stop_event = asyncio.Event()
        while not self._stop_event.is_set():
            await self.poll_once()
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._poll_interval_s,
                )
                break  # stop was signalled
            except TimeoutError:
                pass  # normal interval elapsed

    def stop(self) -> None:
        """Signal the poll loop to exit cleanly."""
        if self._stop_event is not None:
            self._stop_event.set()
