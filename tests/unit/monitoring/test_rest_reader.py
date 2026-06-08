"""CBP5: RestReader only calls ALLOW whitelist; AST + functional tests."""
from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import AsyncMock

from hermes.exchanges.binance_contracts import Kline, KlineInterval
from hermes.monitoring.rest_reader import RestReader

_ALLOW = {"get_klines", "server_time_ms", "ping"}
_REST_READER_SRC = Path("src/hermes/monitoring/rest_reader.py")


# ── CBP5 AST check ────────────────────────────────────────────────────────────


def test_rest_reader_only_calls_whitelist() -> None:
    """CBP5: AST — RestReader._client calls are limited to ALLOW whitelist."""
    src = _REST_READER_SRC.read_text(encoding="utf-8")
    tree = ast.parse(src)
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # Pattern: self._client.<method>(...)
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Attribute)
            and func.value.attr == "_client"
            and func.attr not in _ALLOW
        ):
            violations.append(f"_client.{func.attr}() at L{node.lineno}")
    assert violations == [], f"Non-whitelisted _client calls: {violations}"


# ── Functional tests (mock BinanceRestClient) ──────────────────────────────────


def _make_client(
    ping_raises: Exception | None = None,
    time_raises: Exception | None = None,
    klines_raises: Exception | None = None,
    server_ms: int = 1_700_000_000_000,
    klines: list[Kline] | None = None,
) -> AsyncMock:
    client = AsyncMock()
    if ping_raises:
        client.ping.side_effect = ping_raises
    else:
        client.ping.return_value = {}
    if time_raises:
        client.server_time_ms.side_effect = time_raises
    else:
        client.server_time_ms.return_value = server_ms
    if klines_raises:
        client.get_klines.side_effect = klines_raises
    else:
        client.get_klines.return_value = klines or []
    return client


async def test_read_ping_true_on_success() -> None:
    reader = RestReader(client=_make_client(), symbol="SOLUSDT")
    assert await reader.read_ping() is True


async def test_read_ping_false_on_exception() -> None:
    reader = RestReader(client=_make_client(ping_raises=OSError("timeout")))
    assert await reader.read_ping() is False


async def test_read_server_time_returns_ms() -> None:
    reader = RestReader(client=_make_client(server_ms=12345678))
    assert await reader.read_server_time() == 12345678


async def test_read_server_time_none_on_exception() -> None:
    reader = RestReader(client=_make_client(time_raises=RuntimeError("boom")))
    assert await reader.read_server_time() is None


async def test_read_klines_empty_on_exception() -> None:
    reader = RestReader(client=_make_client(klines_raises=ConnectionError("gone")))
    assert await reader.read_klines() == []


async def test_read_klines_passes_symbol_and_interval() -> None:
    client = _make_client()
    reader = RestReader(client=client, symbol="BTCUSDT")
    await reader.read_klines(limit=5)
    client.get_klines.assert_awaited_once_with(
        symbol="BTCUSDT",
        interval=KlineInterval.HOUR_1,
        limit=5,
    )
