"""CBP6 + CBP7: Alerter delta logic + graceful stop tests."""
from __future__ import annotations

import asyncio
import time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from hermes.monitoring.alerter import Alerter
from hermes.monitoring.rest_reader import RestReader

_D = Decimal  # shorthand for test readability

# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_reader(
    ping_ok: bool = True,
    server_ms: int | None = None,
    price: float | None = None,
) -> AsyncMock:
    reader = AsyncMock(spec=RestReader)
    reader.read_ping.return_value = ping_ok
    reader.read_server_time.return_value = (
        server_ms if server_ms is not None else int(time.time() * 1000)
    )
    if price is not None:
        kline = MagicMock()
        kline.close = Decimal(str(price))
        reader.read_klines.return_value = [kline]
    else:
        reader.read_klines.return_value = []
    return reader


def _make_alerter(
    reader: AsyncMock,
    sent: list[str],
    poll_interval_s: int = 30,
    clock_drift_warn_ms: int = 1000,
    price_move_warn_pct: float = 5.0,
) -> Alerter:
    async def send_fn(msg: str) -> None:
        sent.append(msg)

    return Alerter(
        reader=reader,  # type: ignore[arg-type]
        send_fn=send_fn,
        poll_interval_s=poll_interval_s,
        clock_drift_warn_ms=clock_drift_warn_ms,
        price_move_warn_pct=price_move_warn_pct,
    )


# ── CBP6: ping failure / recovery ─────────────────────────────────────────────


async def test_ping_no_alert_below_threshold() -> None:
    """2 consecutive failures (< threshold 3) → no alert sent."""
    sent: list[str] = []
    alerter = _make_alerter(_make_reader(ping_ok=False), sent)
    await alerter.poll_once()
    await alerter.poll_once()
    assert len(sent) == 0


async def test_ping_alert_at_threshold() -> None:
    """3rd consecutive failure hits threshold → exactly one alert."""
    sent: list[str] = []
    alerter = _make_alerter(_make_reader(ping_ok=False), sent)
    for _ in range(3):
        await alerter.poll_once()
    unreachable = [m for m in sent if "unreachable" in m.lower()]
    assert len(unreachable) == 1


async def test_ping_no_repeat_alert_while_failing() -> None:
    """4th+ failure while already alerted → debounce, no repeat."""
    sent: list[str] = []
    alerter = _make_alerter(_make_reader(ping_ok=False), sent)
    for _ in range(5):
        await alerter.poll_once()
    unreachable = [m for m in sent if "unreachable" in m.lower()]
    assert len(unreachable) == 1


async def test_ping_recovery_rearms() -> None:
    """After ping alert fires, recovery sends recovery message and re-arms."""
    sent: list[str] = []
    reader = _make_reader(ping_ok=False)
    alerter = _make_alerter(reader, sent)

    # Trigger alert
    for _ in range(3):
        await alerter.poll_once()
    assert any("unreachable" in m.lower() for m in sent)

    # Simulate recovery
    reader.read_ping.return_value = True
    await alerter.poll_once()
    assert any("reachable again" in m for m in sent)

    # Re-arm: another 3 failures should alert again
    sent.clear()
    reader.read_ping.return_value = False
    for _ in range(3):
        await alerter.poll_once()
    assert any("unreachable" in m.lower() for m in sent)


# ── CBP6: clock drift ─────────────────────────────────────────────────────────


async def test_drift_alert_when_exceeded() -> None:
    """Drift > threshold → exactly one alert."""
    sent: list[str] = []
    now_ms = int(time.time() * 1000)
    reader = _make_reader(server_ms=now_ms + 2000)  # 2s drift > 1s threshold
    alerter = _make_alerter(reader, sent, clock_drift_warn_ms=1000)

    await alerter.poll_once()
    assert any("drift" in m.lower() and "⚠" in m for m in sent)


async def test_drift_no_repeat_while_drifted() -> None:
    """Drift persists → no second alert (debounce)."""
    sent: list[str] = []
    now_ms = int(time.time() * 1000)
    reader = _make_reader(server_ms=now_ms + 2000)
    alerter = _make_alerter(reader, sent, clock_drift_warn_ms=1000)

    await alerter.poll_once()
    await alerter.poll_once()
    drift_alerts = [m for m in sent if "⚠" in m and "drift" in m.lower()]
    assert len(drift_alerts) == 1


async def test_drift_recovery_rearms() -> None:
    """After drift alert, recovery sends recovery message."""
    sent: list[str] = []
    now_ms = int(time.time() * 1000)
    reader = _make_reader(server_ms=now_ms + 2000)
    alerter = _make_alerter(reader, sent, clock_drift_warn_ms=1000)

    await alerter.poll_once()
    assert any("⚠" in m and "drift" in m.lower() for m in sent)

    reader.read_server_time.return_value = int(time.time() * 1000)  # recovered
    await alerter.poll_once()
    assert any("✅" in m and "drift" in m.lower() for m in sent)


# ── CBP6: price move ──────────────────────────────────────────────────────────


async def test_price_no_alert_on_first_poll() -> None:
    """First poll has no prior snapshot → no price alert."""
    sent: list[str] = []
    alerter = _make_alerter(_make_reader(price=100.0), sent)
    await alerter.poll_once()
    assert len(sent) == 0


async def test_price_alert_on_large_move() -> None:
    """10% move (> 5% threshold) → one alert on second poll."""
    sent: list[str] = []
    reader = _make_reader(price=100.0)
    alerter = _make_alerter(reader, sent, price_move_warn_pct=_D("5.0"))

    await alerter.poll_once()  # establishes baseline

    kline = MagicMock()
    kline.close = Decimal("110")
    reader.read_klines.return_value = [kline]
    await alerter.poll_once()

    assert any("price moved" in m.lower() for m in sent)


async def test_price_no_repeat_while_moved() -> None:
    """Price stays elevated → debounce, no second alert."""
    sent: list[str] = []
    reader = _make_reader(price=100.0)
    alerter = _make_alerter(reader, sent, price_move_warn_pct=_D("5.0"))

    await alerter.poll_once()

    kline = MagicMock()
    kline.close = Decimal("115")
    reader.read_klines.return_value = [kline]
    await alerter.poll_once()
    await alerter.poll_once()

    price_alerts = [m for m in sent if "price moved" in m.lower()]
    assert len(price_alerts) == 1


async def test_price_no_alert_on_small_move() -> None:
    """2% move (< 5% threshold) → no alert."""
    sent: list[str] = []
    reader = _make_reader(price=100.0)
    alerter = _make_alerter(reader, sent, price_move_warn_pct=_D("5.0"))

    await alerter.poll_once()

    kline = MagicMock()
    kline.close = Decimal("102")
    reader.read_klines.return_value = [kline]
    await alerter.poll_once()

    assert len(sent) == 0


# ── CBP6: no false positives ──────────────────────────────────────────────────


async def test_no_false_positives_nominal_operation() -> None:
    """All nominal (ping ok, drift normal, stable price) → zero alerts."""
    sent: list[str] = []
    now_ms = int(time.time() * 1000)
    reader = _make_reader(ping_ok=True, server_ms=now_ms, price=100.0)
    alerter = _make_alerter(reader, sent, clock_drift_warn_ms=1000, price_move_warn_pct=_D("5.0"))

    await alerter.poll_once()
    await alerter.poll_once()  # second poll, same price

    assert len(sent) == 0


# ── CBP7: graceful stop ───────────────────────────────────────────────────────


async def test_graceful_stop_on_stop_call() -> None:
    """Calling stop() causes run() to exit cleanly without exception."""
    sent: list[str] = []
    now_ms = int(time.time() * 1000)
    reader = _make_reader(ping_ok=True, server_ms=now_ms)
    alerter = _make_alerter(reader, sent, poll_interval_s=60)

    task = asyncio.create_task(alerter.run())
    # Yield enough times for poll_once() (3 mock awaits) and wait_for to start
    for _ in range(10):
        await asyncio.sleep(0)
    alerter.stop()
    await asyncio.wait_for(task, timeout=2.0)
    # Task completed without CancelledError or any other exception = graceful ✓


async def test_run_executes_poll_once() -> None:
    """run() calls poll_once at least once before stop()."""
    sent: list[str] = []
    reader = _make_reader()
    alerter = _make_alerter(reader, sent, poll_interval_s=60)

    task = asyncio.create_task(alerter.run())
    for _ in range(10):
        await asyncio.sleep(0)
    alerter.stop()
    await asyncio.wait_for(task, timeout=2.0)

    reader.read_ping.assert_awaited()
