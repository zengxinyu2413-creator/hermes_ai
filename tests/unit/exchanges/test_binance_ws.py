"""Unit tests for BinanceWsClient skeleton (Phase 2.D.3).

Skeleton stage: validates parameter handling, URL resolution, and that
construction does not start any background work. Connection-loop tests
land in Step 2.D.4.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager

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

    def test_uppercase_symbol_rejected(self) -> None:
        with pytest.raises(ValueError, match="lowercase"):
            BinanceWsClient(["SOLUSDT@kline_1m"])

    def test_duplicate_stream_rejected(self) -> None:
        with pytest.raises(ValueError, match="duplicate"):
            BinanceWsClient(["solusdt@kline_1m", "solusdt@kline_1m"])

    def test_accepts_camelcase_stream_type(self) -> None:
        # Binance stream names are case-sensitive: 'bookTicker' is the
        # documented form. The symbol part must be lowercase, but the
        # stream-type part after '@' preserves Binance's mixed case.
        client = BinanceWsClient(["solusdt@bookTicker"])
        assert client.streams == ("solusdt@bookTicker",)

    def test_accepts_mixed_streams_with_camelcase(self) -> None:
        client = BinanceWsClient(
            ["solusdt@kline_1m", "solusdt@bookTicker"]
        )
        assert client.streams == ("solusdt@kline_1m", "solusdt@bookTicker")

    def test_missing_at_sign_rejected(self) -> None:
        with pytest.raises(ValueError, match="must contain"):
            BinanceWsClient(["solusdt"])

    def test_invalid_stream_type_chars_rejected(self) -> None:
        # Stream-type part must be [a-zA-Z0-9_]+: no spaces, hyphens, etc.
        with pytest.raises(ValueError, match="must match"):
            BinanceWsClient(["solusdt@book ticker"])

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


# ====================================================================== #
# Phase 2.D.4b-i — Mock WebSocket infrastructure                          #
# ====================================================================== #
#
# `websockets` doesn't ship a MockTransport equivalent like httpx, so we
# build our own. The real WebSocketClientProtocol is simultaneously:
#   - an async context manager  (`async with websockets.connect(url) as ws`)
#   - an async iterator         (`async for raw in ws: ...`)
#   - an object with recv/send/close methods
#
# MockWebSocketConnection covers all three surfaces. Tests provide a list
# of frames the mock will deliver in order, optionally followed by an
# exception to simulate disconnection.
#
# `_mock_connect_factory` is the async-context-manager that monkeypatches
# `websockets.connect`. It yields the mock connection on __aenter__ and
# closes it on __aexit__, matching the real API.


class MockWebSocketConnection:
    """In-memory stand-in for websockets.WebSocketClientProtocol.

    Parameters
    ----------
    frames:
        Strings to deliver, in order, on successive recv / __anext__ calls.
    close_exc:
        If provided, raised after the last frame is consumed. Use this to
        simulate server-side disconnection (e.g. ConnectionClosedError).
        If None, the iterator raises ConnectionClosedOK after the last
        frame to simulate a clean server close.
    """

    def __init__(
        self,
        frames: list[str],
        close_exc: BaseException | None = None,
    ) -> None:
        self._frames: list[str] = list(frames)
        self._close_exc = close_exc
        self._closed: bool = False
        self.sent: list[str] = []  # tests can inspect what we sent

    def __aiter__(self) -> "MockWebSocketConnection":
        return self

    async def __anext__(self) -> str:
        # Yield to the event loop so cancellation can interleave realistically.
        await asyncio.sleep(0)
        if self._frames:
            return self._frames.pop(0)
        # Out of frames — decide how to terminate.
        # NOTE: The real websockets library catches ConnectionClosedOK inside
        # its __aiter__ and converts it to StopAsyncIteration so `async for`
        # ends cleanly. We mirror that here: clean close ends iteration;
        # explicit close_exc (e.g. ConnectionClosedError) propagates.
        if self._close_exc is not None:
            raise self._close_exc
        raise StopAsyncIteration

    async def recv(self) -> str:
        # recv() has different semantics from async-for: it raises
        # ConnectionClosedOK when the connection is closed (matching the
        # real websockets API). Tests that need recv-after-close should
        # expect ConnectionClosedOK; tests that iterate via async-for
        # should expect a clean end.
        await asyncio.sleep(0)
        if self._frames:
            return self._frames.pop(0)
        if self._close_exc is not None:
            raise self._close_exc
        from websockets.exceptions import ConnectionClosedOK
        raise ConnectionClosedOK(None, None)

    async def send(self, data: str) -> None:
        self.sent.append(data)

    async def close(self) -> None:
        self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed


@asynccontextmanager
async def _mock_connect_factory(
    frames: list[str],
    close_exc: BaseException | None = None,
):
    """Async-context-manager that yields a MockWebSocketConnection.

    Drop-in replacement for `websockets.connect(url, ...)`. Tests patch
    `hermes.exchanges.binance_ws.websockets.connect` with a lambda that
    returns this context manager pre-loaded with the desired frames.
    """
    conn = MockWebSocketConnection(frames, close_exc=close_exc)
    try:
        yield conn
    finally:
        await conn.close()


# ====================================================================== #
# Phase 2.D.4b-i — Mock infrastructure sanity tests                       #
# ====================================================================== #


class TestMockWebSocketSanity:
    """Verify the mock itself works before we rely on it for business tests."""

    @pytest.mark.asyncio
    async def test_mock_delivers_frames_in_order(self) -> None:
        async with _mock_connect_factory(["a", "b", "c"]) as ws:
            received = [m async for m in ws]
        assert received == ["a", "b", "c"]

    @pytest.mark.asyncio
    async def test_mock_clean_close_after_frames(self) -> None:
        # With no close_exc, iteration should end cleanly (StopAsyncIteration)
        # via ConnectionClosedOK being raised internally and async-for swallowing
        # it the same way the real library would.
        from websockets.exceptions import ConnectionClosedOK
        async with _mock_connect_factory(["only_frame"]) as ws:
            assert await ws.recv() == "only_frame"
            with pytest.raises(ConnectionClosedOK):
                await ws.recv()

    @pytest.mark.asyncio
    async def test_mock_custom_close_exception(self) -> None:
        # Tests can inject specific disconnect exceptions to drive 2.D.5
        # reconnect logic later.
        from websockets.exceptions import ConnectionClosedError
        exc = ConnectionClosedError(None, None)
        async with _mock_connect_factory(["a"], close_exc=exc) as ws:
            assert await ws.recv() == "a"
            with pytest.raises(ConnectionClosedError):
                await ws.recv()

    @pytest.mark.asyncio
    async def test_mock_records_sent_data(self) -> None:
        async with _mock_connect_factory(["x"]) as ws:
            await ws.send("hello")
            await ws.send("world")
        assert ws.sent == ["hello", "world"]

    @pytest.mark.asyncio
    async def test_mock_closes_on_context_exit(self) -> None:
        async with _mock_connect_factory([]) as ws:
            assert ws.closed is False
        assert ws.closed is True


# ====================================================================== #


# ====================================================================== #
# Phase 2.D.4b-ii - Read loop + lifecycle integration tests              #
# ====================================================================== #


def _patch_connect(monkeypatch, frames, close_exc=None):
    """Helper: swap binance_ws.websockets.connect for our mock factory."""
    def _fake_connect(url, **kwargs):
        return _mock_connect_factory(frames, close_exc=close_exc)
    monkeypatch.setattr(
        "hermes.exchanges.binance_ws.websockets.connect",
        _fake_connect,
    )


class TestReadLoopBasics:
    @pytest.mark.asyncio
    async def test_yields_three_klines_in_order(self, monkeypatch) -> None:
        from hermes.exchanges.binance_contracts import StreamKind
        frames = [
            _make_kline_frame(),
            _make_kline_frame(),
            _make_kline_frame(),
        ]
        _patch_connect(monkeypatch, frames)

        received = []
        async with BinanceWsClient(["solusdt@kline_1m"]) as ws:
            async for msg in ws.stream():
                received.append(msg)

        assert len(received) == 3
        assert all(m.kind is StreamKind.KLINE for m in received)
        assert all(m.kline is not None for m in received)


class TestReadLoopMixedTypes:
    @pytest.mark.asyncio
    async def test_mixed_stream_types_dispatched_correctly(self, monkeypatch) -> None:
        from hermes.exchanges.binance_contracts import StreamKind
        frames = [
            _make_kline_frame(),
            _make_bookticker_frame(),
            _make_trade_frame(),
        ]
        _patch_connect(monkeypatch, frames)

        received = []
        async with BinanceWsClient(
            ["solusdt@kline_1m", "solusdt@bookticker", "solusdt@trade"]
        ) as ws:
            async for msg in ws.stream():
                received.append(msg)

        assert [m.kind for m in received] == [
            StreamKind.KLINE,
            StreamKind.BOOK_TICKER,
            StreamKind.TRADE,
        ]
        assert received[0].kline is not None
        assert received[1].book_ticker is not None
        assert received[2].trade is not None


class TestReadLoopGracefulClose:
    @pytest.mark.asyncio
    async def test_clean_server_close_ends_stream_without_raising(
        self, monkeypatch
    ) -> None:
        _patch_connect(monkeypatch, [])

        received = []
        async with BinanceWsClient(["solusdt@kline_1m"]) as ws:
            async for msg in ws.stream():
                received.append(msg)

        assert received == []


class TestReadLoopGarbageDoesNotCrash:
    @pytest.mark.asyncio
    async def test_garbage_frame_produces_unknown_not_crash(
        self, monkeypatch
    ) -> None:
        from hermes.exchanges.binance_contracts import StreamKind
        frames = [
            "not json at all {{{",
            _make_kline_frame(),
        ]
        _patch_connect(monkeypatch, frames)

        received = []
        async with BinanceWsClient(["solusdt@kline_1m"]) as ws:
            async for msg in ws.stream():
                received.append(msg)

        assert len(received) == 2
        assert received[0].kind is StreamKind.UNKNOWN
        assert received[1].kind is StreamKind.KLINE


class TestZeroMessageLoss:
    """Verifies that messages queued before connection-end are still delivered.

    This is the design property that motivated option-A drain semantics in
    stream(): if the read loop pushes N messages then the connection drops,
    the consumer must still receive all N.
    """

    @pytest.mark.asyncio
    async def test_all_messages_delivered_even_after_disconnect(
        self, monkeypatch
    ) -> None:
        from websockets.exceptions import ConnectionClosedError
        frames = [_make_kline_frame() for _ in range(10)]
        _patch_connect(
            monkeypatch, frames,
            close_exc=ConnectionClosedError(None, None),
        )

        received = []
        async with BinanceWsClient(["solusdt@kline_1m"]) as ws:
            async for msg in ws.stream():
                received.append(msg)

        assert len(received) == 10


class TestLifecycleInvariants:
    @pytest.mark.asyncio
    async def test_main_task_set_inside_context(self, monkeypatch) -> None:
        _patch_connect(monkeypatch, [])
        ws = BinanceWsClient(["solusdt@kline_1m"])
        assert ws._main_task is None
        async with ws:
            assert ws._main_task is not None

    @pytest.mark.asyncio
    async def test_closed_flag_set_after_exit(self, monkeypatch) -> None:
        _patch_connect(monkeypatch, [])
        ws = BinanceWsClient(["solusdt@kline_1m"])
        async with ws:
            pass
        assert ws._closed is True

    @pytest.mark.asyncio
    async def test_reuse_after_close_raises(self, monkeypatch) -> None:
        _patch_connect(monkeypatch, [])
        ws = BinanceWsClient(["solusdt@kline_1m"])
        async with ws:
            pass
        with pytest.raises(RuntimeError, match="cannot be reused"):
            async with ws:
                pass

    @pytest.mark.asyncio
    async def test_stream_outside_context_raises(self) -> None:
        ws = BinanceWsClient(["solusdt@kline_1m"])
        with pytest.raises(RuntimeError, match="can only be called inside"):
            async for _ in ws.stream():
                pass


class TestBackpressureBoundedQueue:
    @pytest.mark.asyncio
    async def test_small_queue_does_not_drop_messages(self, monkeypatch) -> None:
        """With queue_max_size=2 and 10 frames, slow consumer still gets all 10."""
        from hermes.exchanges.binance_contracts import StreamKind
        frames = [_make_kline_frame() for _ in range(10)]
        _patch_connect(monkeypatch, frames)

        received = []
        async with BinanceWsClient(
            ["solusdt@kline_1m"], queue_max_size=2
        ) as ws:
            async for msg in ws.stream():
                received.append(msg)
                await asyncio.sleep(0.001)

        assert len(received) == 10
        assert all(m.kind is StreamKind.KLINE for m in received)
