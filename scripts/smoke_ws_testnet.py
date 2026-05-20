"""Phase 2.E.1 — Testnet WebSocket smoke test.

Subscribes to three SOL/USDT market-data streams on Binance testnet,
runs for 60 seconds, and prints WsMetrics snapshots every 10 seconds.

Pass criteria (evaluated at end of run):
  - messages_received_total > 0
  - all three StreamKind values present in messages_by_kind with count > 0
  - reconnect_count == 0

Usage (from repo root, venv active):
    python scripts/smoke_ws_testnet.py
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

# Allow running from repo root without installing the package.
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from hermes.exchanges.binance_contracts import StreamKind
from hermes.exchanges.binance_credentials import BinanceCredentials, BinanceEnvironment
from hermes.exchanges.binance_ws import BinanceWsClient

_STREAMS = [
    "solusdt@kline_1m",
    "solusdt@bookTicker",
    "solusdt@trade",
]
_RUN_SECONDS = 60
_PRINT_INTERVAL = 10


def _fmt_metrics(ws: BinanceWsClient, elapsed: float) -> str:
    m = ws.metrics
    by_kind = {k.name: v for k, v in m.messages_by_kind.items()}
    uptime = (
        f"{time.monotonic() - m.connected_since:.1f}s"
        if m.connected_since is not None
        else "disconnected"
    )
    return (
        f"[t+{elapsed:.0f}s] total={m.messages_received_total}"
        f"  by_kind={by_kind}"
        f"  reconnects={m.reconnect_count}"
        f"  uptime={uptime}"
    )


def _evaluate(ws: BinanceWsClient) -> bool:
    m = ws.metrics
    ok = True

    if m.messages_received_total == 0:
        print("FAIL  messages_received_total == 0")
        ok = False
    else:
        print(f"PASS  messages_received_total = {m.messages_received_total}")

    expected_kinds = {StreamKind.KLINE, StreamKind.BOOK_TICKER, StreamKind.TRADE}
    missing = expected_kinds - set(m.messages_by_kind.keys())
    zero_count = {k for k, v in m.messages_by_kind.items() if k in expected_kinds and v == 0}
    bad_kinds = missing | zero_count
    if bad_kinds:
        print(f"FAIL  missing or zero StreamKind(s): {[k.name for k in bad_kinds]}")
        ok = False
    else:
        present = {k.name: m.messages_by_kind[k] for k in expected_kinds}
        print(f"PASS  all three kinds present: {present}")

    if m.reconnect_count != 0:
        print(f"FAIL  reconnect_count = {m.reconnect_count} (expected 0)")
        ok = False
    else:
        print("PASS  reconnect_count == 0")

    return ok


async def main() -> None:
    # Preflight: verify testnet credentials are configured.
    creds = BinanceCredentials()
    api_key, _ = creds.get_key_pair(BinanceEnvironment.TESTNET)
    print(f"Credentials OK  key={api_key[:8]}***")

    print(f"Connecting to Binance TESTNET, streams: {_STREAMS}")
    start = time.monotonic()

    async with BinanceWsClient(_STREAMS, env=BinanceEnvironment.TESTNET) as ws:
        print_at = start + _PRINT_INTERVAL

        async def _consume() -> None:
            async for _msg in ws.stream():
                pass  # metrics are updated inside the client

        consume_task = asyncio.create_task(_consume())

        try:
            while True:
                now = time.monotonic()
                elapsed = now - start
                if elapsed >= _RUN_SECONDS:
                    break
                if now >= print_at:
                    print(_fmt_metrics(ws, elapsed))
                    print_at += _PRINT_INTERVAL
                await asyncio.sleep(0.1)
        finally:
            consume_task.cancel()
            try:
                await consume_task
            except asyncio.CancelledError:
                pass

    elapsed = time.monotonic() - start
    print(f"\n--- Final snapshot after {elapsed:.1f}s ---")
    print(_fmt_metrics(ws, elapsed))
    print("\n--- Pass/Fail ---")
    passed = _evaluate(ws)
    print(f"\n{'SMOKE TEST PASSED' if passed else 'SMOKE TEST FAILED'}")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    asyncio.run(main())
