"""Unit tests for BinanceWsClient skeleton (Phase 2.D.3).

Skeleton stage: validates parameter handling, URL resolution, and that
construction does not start any background work. Connection-loop tests
land in Step 2.D.4.
"""

from __future__ import annotations

import asyncio

import pytest

from hermes.exchanges.binance_credentials import BinanceEnvironment
from hermes.exchanges.binance_ws import BinanceWsClient


# ====================================================================== #
# Construction & validation                                              #
# ====================================================================== #


class TestStreamsValidation:
    def test_accepts_single_stream(self) -> None:
        ws = BinanceWsClient(["solusdt@kline_1m"])
        assert ws.streams == ("solusdt@kline_1m",)

    def test_accepts_multiple_streams(self) -> None:
        ws = BinanceWsClient(
            ["solusdt@kline_1m", "solusdt@bookticker", "solusdt@trade"]
        )
        assert len(ws.streams) == 3

    def test_streams_property_is_tuple(self) -> None:
        ws = BinanceWsClient(["solusdt@kline_1m"])
        assert isinstance(ws.streams, tuple)

    def test_empty_list_rejected(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            BinanceWsClient([])

    def test_non_list_rejected(self) -> None:
        with pytest.raises(TypeError, match="must be a list"):
            BinanceWsClient("solusdt@kline_1m")  # type: ignore[arg-type]

    def test_non_string_entry_rejected(self) -> None:
        with pytest.raises(TypeError, match="must be str"):
            BinanceWsClient([123])  # type: ignore[list-item]

    def test_empty_string_entry_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            BinanceWsClient([""])

    def test_uppercase_stream_rejected(self) -> None:
        with pytest.raises(ValueError, match="lowercase"):
            BinanceWsClient(["SOLUSDT@kline_1m"])

    def test_duplicate_stream_rejected(self) -> None:
        with pytest.raises(ValueError, match="duplicate"):
            BinanceWsClient(["solusdt@kline_1m", "solusdt@kline_1m"])

    def test_too_many_streams_rejected(self) -> None:
        # 201 unique streams > cap of 200
        many = [f"solusdt@kline_{i}m" for i in range(201)]
        with pytest.raises(ValueError, match="exceeds cap"):
            BinanceWsClient(many)


class TestQueueSizeValidation:
    def test_default_queue_size(self) -> None:
        ws = BinanceWsClient(["solusdt@kline_1m"])
        assert ws._queue_max_size == 10_000

    def test_custom_queue_size(self) -> None:
        ws = BinanceWsClient(["solusdt@kline_1m"], queue_max_size=500)
        assert ws._queue_max_size == 500

    def test_zero_queue_size_rejected(self) -> None:
        with pytest.raises(ValueError, match=">= 1"):
            BinanceWsClient(["solusdt@kline_1m"], queue_max_size=0)

    def test_negative_queue_size_rejected(self) -> None:
        with pytest.raises(ValueError, match=">= 1"):
            BinanceWsClient(["solusdt@kline_1m"], queue_max_size=-1)

    def test_non_int_queue_size_rejected(self) -> None:
        with pytest.raises(TypeError, match="must be int"):
            BinanceWsClient(
                ["solusdt@kline_1m"], queue_max_size=1.5  # type: ignore[arg-type]
            )

    def test_bool_queue_size_rejected(self) -> None:
        # bool is a subclass of int — reject it explicitly
        with pytest.raises(TypeError, match="must be int"):
            BinanceWsClient(
                ["solusdt@kline_1m"], queue_max_size=True  # type: ignore[arg-type]
            )


# ====================================================================== #
# URL resolution                                                         #
# ====================================================================== #


class TestUrl:
    def test_testnet_url(self) -> None:
        ws = BinanceWsClient(
            ["solusdt@kline_1m"], env=BinanceEnvironment.TESTNET
        )
        assert ws.url == (
            "wss://stream.testnet.binance.vision/stream"
            "?streams=solusdt@kline_1m"
        )

    def test_mainnet_url(self) -> None:
        ws = BinanceWsClient(
            ["solusdt@kline_1m"], env=BinanceEnvironment.MAINNET
        )
        assert ws.url == (
            "wss://stream.binance.com:9443/stream"
            "?streams=solusdt@kline_1m"
        )

    def test_multiple_streams_joined_by_slash(self) -> None:
        ws = BinanceWsClient(
            ["solusdt@kline_1m", "solusdt@bookticker", "solusdt@trade"]
        )
        assert ws.url.endswith(
            "?streams=solusdt@kline_1m/solusdt@bookticker/solusdt@trade"
        )

    def test_default_env_is_testnet(self) -> None:
        ws = BinanceWsClient(["solusdt@kline_1m"])
        assert ws.env is BinanceEnvironment.TESTNET


# ====================================================================== #
# Lifecycle invariants                                                   #
# ====================================================================== #


class TestLifecycleSkeleton:
    def test_construction_does_not_create_queue(self) -> None:
        # Queue must be loop-bound, so it's deferred to __aenter__.
        ws = BinanceWsClient(["solusdt@kline_1m"])
        assert ws._queue is None

    def test_construction_does_not_start_task(self) -> None:
        ws = BinanceWsClient(["solusdt@kline_1m"])
        assert ws._main_task is None
        assert ws.is_running is False

    def test_construction_outside_event_loop(self) -> None:
        # Should not require a running event loop.
        # If this test runs, construction succeeded loop-free.
        ws = BinanceWsClient(["solusdt@kline_1m"])
        assert ws is not None

    def test_repr_format(self) -> None:
        ws = BinanceWsClient(
            ["solusdt@kline_1m", "solusdt@trade"],
            env=BinanceEnvironment.MAINNET,
        )
        r = repr(ws)
        assert "BinanceWsClient" in r
        assert "mainnet" in r
        assert "streams=2" in r
        assert "running=False" in r

    @pytest.mark.asyncio
    async def test_aenter_raises_not_implemented(self) -> None:
        # Step 2.D.4 will replace this with a real connection.
        ws = BinanceWsClient(["solusdt@kline_1m"])
        with pytest.raises(NotImplementedError, match="Step 2.D.4"):
            await ws.__aenter__()

    @pytest.mark.asyncio
    async def test_stream_raises_not_implemented(self) -> None:
        ws = BinanceWsClient(["solusdt@kline_1m"])
        with pytest.raises(NotImplementedError, match="Step 2.D.4"):
            await ws.stream()