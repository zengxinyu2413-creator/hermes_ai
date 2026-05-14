"""Unit tests for BinanceWsClient skeleton (Phase 2.D.3).

Skeleton stage: validates parameter handling, URL resolution, and that
construction does not start any background work. Connection-loop tests
land in Step 2.D.4.
"""

from __future__ import annotations

import asyncio
import json

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

# ====================================================================== #
# Phase 2.D.4a — Stream classification                                   #
# ====================================================================== #


class TestClassifyStream:
    def test_kline_stream(self) -> None:
        from hermes.exchanges.binance_contracts import StreamKind
        assert BinanceWsClient._classify_stream(
            "solusdt@kline_1m"
        ) is StreamKind.KLINE

    def test_kline_stream_various_intervals(self) -> None:
        from hermes.exchanges.binance_contracts import StreamKind
        for interval in ["1m", "5m", "15m", "1h", "4h", "1d"]:
            assert BinanceWsClient._classify_stream(
                f"solusdt@kline_{interval}"
            ) is StreamKind.KLINE, f"failed on interval {interval}"

    def test_bookticker_stream_lowercase(self) -> None:
        from hermes.exchanges.binance_contracts import StreamKind
        assert BinanceWsClient._classify_stream(
            "solusdt@bookticker"
        ) is StreamKind.BOOK_TICKER

    def test_bookticker_stream_camelcase(self) -> None:
        from hermes.exchanges.binance_contracts import StreamKind
        assert BinanceWsClient._classify_stream(
            "solusdt@bookTicker"
        ) is StreamKind.BOOK_TICKER

    def test_trade_stream(self) -> None:
        from hermes.exchanges.binance_contracts import StreamKind
        assert BinanceWsClient._classify_stream(
            "solusdt@trade"
        ) is StreamKind.TRADE

    def test_depth_stream_is_unknown(self) -> None:
        from hermes.exchanges.binance_contracts import StreamKind
        assert BinanceWsClient._classify_stream(
            "solusdt@depth20"
        ) is StreamKind.UNKNOWN

    def test_no_at_sign_is_unknown(self) -> None:
        from hermes.exchanges.binance_contracts import StreamKind
        assert BinanceWsClient._classify_stream(
            "garbage"
        ) is StreamKind.UNKNOWN

    def test_empty_string_is_unknown(self) -> None:
        from hermes.exchanges.binance_contracts import StreamKind
        assert BinanceWsClient._classify_stream("") is StreamKind.UNKNOWN


# ====================================================================== #
# Phase 2.D.4a — Message parsing                                         #
# ====================================================================== #


def _make_kline_frame(
    symbol: str = "SOLUSDT",
    interval: str = "1m",
    is_closed: bool = True,
) -> str:
    """Build a realistic Binance combined-stream kline frame as JSON string."""
    return json.dumps({
        "stream": f"{symbol.lower()}@kline_{interval}",
        "data": {
            "e": "kline",
            "E": 1747200000123,
            "s": symbol,
            "k": {
                "t": 1747200000000,
                "T": 1747200059999,
                "s": symbol,
                "i": interval,
                "f": 100,
                "L": 200,
                "o": "150.00",
                "c": "150.50",
                "h": "151.00",
                "l": "149.50",
                "v": "12.345",
                "n": 42,
                "x": is_closed,
                "q": "1853.00",
                "V": "6.0",
                "Q": "900.0",
                "B": "0",
            },
        },
    })


def _make_bookticker_frame(symbol: str = "SOLUSDT") -> str:
    return json.dumps({
        "stream": f"{symbol.lower()}@bookticker",
        "data": {
            "u": 400900217,
            "s": symbol,
            "b": "150.00",
            "B": "10.5",
            "a": "150.01",
            "A": "5.2",
        },
    })


def _make_trade_frame(symbol: str = "SOLUSDT") -> str:
    return json.dumps({
        "stream": f"{symbol.lower()}@trade",
        "data": {
            "e": "trade",
            "E": 1747200000123,
            "s": symbol,
            "t": 12345,
            "p": "150.00",
            "q": "0.1",
            "T": 1747200000000,
            "m": False,
        },
    })


class TestParseMessageHappyPath:
    def test_parse_kline(self) -> None:
        from hermes.exchanges.binance_contracts import StreamKind
        raw = _make_kline_frame()
        msg = BinanceWsClient._parse_message(raw)
        assert msg.kind is StreamKind.KLINE
        assert msg.stream == "solusdt@kline_1m"
        assert msg.kline is not None
        assert msg.kline.symbol == "SOLUSDT"
        assert msg.kline.interval == "1m"
        assert msg.kline.is_closed is True
        assert msg.book_ticker is None
        assert msg.trade is None

    def test_parse_kline_in_progress(self) -> None:
        raw = _make_kline_frame(is_closed=False)
        msg = BinanceWsClient._parse_message(raw)
        assert msg.kline is not None
        assert msg.kline.is_closed is False

    def test_parse_bookticker(self) -> None:
        from hermes.exchanges.binance_contracts import StreamKind
        raw = _make_bookticker_frame()
        msg = BinanceWsClient._parse_message(raw)
        assert msg.kind is StreamKind.BOOK_TICKER
        assert msg.book_ticker is not None
        assert msg.book_ticker.symbol == "SOLUSDT"
        assert msg.kline is None
        assert msg.trade is None

    def test_parse_trade(self) -> None:
        from hermes.exchanges.binance_contracts import StreamKind
        raw = _make_trade_frame()
        msg = BinanceWsClient._parse_message(raw)
        assert msg.kind is StreamKind.TRADE
        assert msg.trade is not None
        assert msg.trade.is_buyer_maker is False


class TestParseMessageErrorPaths:
    def test_invalid_json_returns_unknown(self) -> None:
        from hermes.exchanges.binance_contracts import StreamKind
        msg = BinanceWsClient._parse_message("not json at all {{{")
        assert msg.kind is StreamKind.UNKNOWN
        assert msg.stream == ""
        assert msg.raw == {}

    def test_non_object_envelope_returns_unknown(self) -> None:
        from hermes.exchanges.binance_contracts import StreamKind
        for raw in ["[]", "42", '"hello"', "null"]:
            msg = BinanceWsClient._parse_message(raw)
            assert msg.kind is StreamKind.UNKNOWN, f"failed on {raw!r}"

    def test_missing_stream_field_returns_unknown(self) -> None:
        from hermes.exchanges.binance_contracts import StreamKind
        raw = json.dumps({"data": {"foo": "bar"}})
        msg = BinanceWsClient._parse_message(raw)
        assert msg.kind is StreamKind.UNKNOWN
        assert msg.raw == {"data": {"foo": "bar"}}

    def test_missing_data_field_returns_unknown(self) -> None:
        from hermes.exchanges.binance_contracts import StreamKind
        raw = json.dumps({"stream": "solusdt@kline_1m"})
        msg = BinanceWsClient._parse_message(raw)
        assert msg.kind is StreamKind.UNKNOWN
        assert msg.stream == "solusdt@kline_1m"

    def test_unknown_stream_type_returns_unknown(self) -> None:
        from hermes.exchanges.binance_contracts import StreamKind
        raw = json.dumps({
            "stream": "solusdt@depth20",
            "data": {"bids": [], "asks": []},
        })
        msg = BinanceWsClient._parse_message(raw)
        assert msg.kind is StreamKind.UNKNOWN
        assert msg.stream == "solusdt@depth20"

    def test_kline_missing_inner_k_returns_unknown(self) -> None:
        from hermes.exchanges.binance_contracts import StreamKind
        raw = json.dumps({
            "stream": "solusdt@kline_1m",
            "data": {"e": "kline", "s": "SOLUSDT"},
        })
        msg = BinanceWsClient._parse_message(raw)
        assert msg.kind is StreamKind.UNKNOWN
        assert msg.kline is None


class TestParseMessageInvariants:
    """The single most important property: parse never raises."""

    @pytest.mark.parametrize("raw", [
        "",
        " ",
        "null",
        "{}",
        "[]",
        '{"stream": 1}',
        '{"stream": "", "data": {}}',
        '{"stream": "solusdt@kline_1m", "data": null}',
        '{"stream": "solusdt@kline_1m", "data": []}',
        "{not valid",
        '{"a": "b"}',
        "0",
        "true",
    ])
    def test_never_raises_on_garbage(self, raw: str) -> None:
        from hermes.exchanges.binance_contracts import StreamKind
        msg = BinanceWsClient._parse_message(raw)
        assert msg.kind is StreamKind.UNKNOWN
