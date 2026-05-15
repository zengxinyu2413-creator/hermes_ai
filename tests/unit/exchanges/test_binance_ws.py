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


class TestComputeBackoffDelay:
    def test_attempt_1_returns_zero(self) -> None:
        # attempt 1 = immediate retry: most blips recover within milliseconds
        assert BinanceWsClient._compute_backoff_delay(1) == 0.0
        assert BinanceWsClient._compute_backoff_delay(0) == 0.0
        assert BinanceWsClient._compute_backoff_delay(-5) == 0.0

    def test_attempt_grows_exponentially_within_jitter_band(self) -> None:
        # For attempt N>=2, base = 2^(N-2). Jitter is +/-25%, so the result
        # must land in [0.75*base, 1.25*base]. We sample 200 times per
        # attempt to confirm the distribution stays within bounds.
        for attempt, expected_base in [(2, 1), (3, 2), (4, 4), (5, 8), (6, 16)]:
            samples = [
                BinanceWsClient._compute_backoff_delay(attempt)
                for _ in range(200)
            ]
            lower = expected_base * 0.75
            upper = expected_base * 1.25
            for delay in samples:
                assert lower <= delay <= upper, (
                    f"attempt={attempt} expected [{lower}, {upper}], got {delay}"
                )

    def test_capped_at_60_seconds(self) -> None:
        # attempt 8 onwards: base = min(2^6=64, 60) = 60.
        # With +/-25% jitter, upper bound is 75s.
        for attempt in (8, 10, 20, 100):
            samples = [
                BinanceWsClient._compute_backoff_delay(attempt)
                for _ in range(200)
            ]
            for delay in samples:
                assert 45.0 <= delay <= 75.0, (
                    f"attempt={attempt} should cap near 60s, got {delay}"
                )


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
        hang_after_frames: bool = False,
    ) -> None:
        self._frames: list[str] = list(frames)
        self._close_exc = close_exc
        self._hang_after_frames = hang_after_frames
        self._closed: bool = False
        self.sent: list[str] = []  # tests can inspect what we sent

    def __aiter__(self) -> "MockWebSocketConnection":
        return self

    async def __anext__(self) -> str:
        # Yield to the event loop so cancellation can interleave realistically.
        await asyncio.sleep(0)
        if self._frames:
            return self._frames.pop(0)
        if self._hang_after_frames:
            # Simulate an idle but healthy connection: block forever
            # until the surrounding task is cancelled by the caller.
            await asyncio.Event().wait()
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
        if self._hang_after_frames:
            await asyncio.Event().wait()
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
    hang_after_frames: bool = False,
):
    """Async-context-manager that yields a MockWebSocketConnection.

    Drop-in replacement for `websockets.connect(url, ...)`. Tests patch
    `hermes.exchanges.binance_ws.websockets.connect` with a lambda that
    returns this context manager pre-loaded with the desired frames.
    """
    conn = MockWebSocketConnection(frames, close_exc=close_exc, hang_after_frames=hang_after_frames)
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


def _patch_connect_scripts(monkeypatch, scripts):
    """Multi-attempt variant of ``_patch_connect`` for reconnect tests.

    Each entry in ``scripts`` describes one ``websockets.connect()`` call:

        {"frames": list[str], "close_exc": BaseException | None}

    The Nth ``connect()`` call yields ``scripts[N-1]``; after the list is
    exhausted the last entry repeats so a runaway reconnect loop is still
    well-defined. Returns a single-element list whose [0] tracks how many
    times ``connect()`` was invoked.
    """
    call_count = [0]

    def _fake_connect(url, **kwargs):
        idx = min(call_count[0], len(scripts) - 1)
        call_count[0] += 1
        script = scripts[idx]
        return _mock_connect_factory(
            list(script.get("frames", [])),
            close_exc=script.get("close_exc"),
            hang_after_frames=script.get("hang_after_frames", False),
        )

    monkeypatch.setattr(
        "hermes.exchanges.binance_ws.websockets.connect",
        _fake_connect,
    )
    return call_count


@pytest.fixture
def bypass_reconnect(monkeypatch):
    """Replace _run_with_reconnect with _run_one for read-loop tests.

    Read-loop tests verify frame parsing/dispatch within a single connection.
    Reconnect behavior is exercised separately (see TestReconnect). With
    reconnect active, finite mock frames cause an infinite reconnect loop
    that obscures these tests' actual concern.
    """
    monkeypatch.setattr(
        "hermes.exchanges.binance_ws.BinanceWsClient._run_with_reconnect",
        BinanceWsClient._run_one,
    )


@pytest.fixture
def no_jitter(monkeypatch):
    """Zero out backoff jitter so reconnect delays are deterministic.

    ``_compute_backoff_delay`` multiplies the base delay by
    ``(1 + random.uniform(-0.25, 0.25))``. Patching ``random.uniform``
    to return 0.0 makes the multiplier exactly 1 and the resulting
    sequence is the pure ``[0, 1, 2, 4, 8, ...]`` capped at 60.
    """
    monkeypatch.setattr(
        "hermes.exchanges.binance_ws.random.uniform",
        lambda _a, _b: 0.0,
    )


@pytest.fixture
def sleep_calls(monkeypatch):
    """Record every asyncio.sleep call in binance_ws and skip the wait.

    Captures the real asyncio.sleep reference BEFORE patching to avoid
    the recursion trap where the replacement function would look up
    asyncio.sleep again and find itself (because
    ``hermes.exchanges.binance_ws.asyncio`` is the same module object
    as the test's ``asyncio``).

    Returns the list of recorded delays; tests can inspect the prefix
    to assert on the backoff schedule.
    """
    calls: list[float] = []
    real_sleep = asyncio.sleep

    async def _recording_sleep(delay):
        calls.append(delay)
        await real_sleep(0)

    monkeypatch.setattr(
        "hermes.exchanges.binance_ws.asyncio.sleep",
        _recording_sleep,
    )
    return calls


class TestReadLoopBasics:
    @pytest.mark.asyncio
    async def test_yields_three_klines_in_order(self, monkeypatch, bypass_reconnect) -> None:
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
    async def test_mixed_stream_types_dispatched_correctly(self, monkeypatch, bypass_reconnect) -> None:
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
        self, monkeypatch, bypass_reconnect
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
        self, monkeypatch, bypass_reconnect
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
    async def test_small_queue_does_not_drop_messages(self, monkeypatch, bypass_reconnect) -> None:
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


class TestReconnect:
    """End-to-end reconnect behavior (Phase 2.D.5b-iv).

    These tests exercise ``_run_with_reconnect`` with real timing semantics:
      * ``asyncio.sleep`` is patched to record delays without actually waiting.
      * ``random.uniform`` is patched to zero out jitter for deterministic
        backoff assertions where needed.

    Note: ``bypass_reconnect`` is intentionally *not* used here.
    """

    @pytest.mark.asyncio
    async def test_zero_message_loss_across_reconnect(self, monkeypatch) -> None:
        """All 10 frames are delivered to the consumer across 3 connections.

        Setup: server delivers 3 frames, drops; then 3 more, drops; then 4
        more. Consumer iterates ``ws.stream()`` and must see all 10 messages
        with no loss and no duplication.
        """
        from websockets.exceptions import ConnectionClosedError
        from hermes.exchanges.binance_contracts import StreamKind

        # Patch asyncio.sleep so reconnect backoff does not block the test.
        # Capture the real sleep before patching to avoid recursing into
        # our own replacement.
        real_sleep = asyncio.sleep
        async def _fast_sleep(_delay: float) -> None:
            await real_sleep(0)
        monkeypatch.setattr(
            "hermes.exchanges.binance_ws.asyncio.sleep",
            _fast_sleep,
        )

        # Three connection attempts: 3 + 3 + 4 frames, each ending with a
        # ConnectionClosedError that _run_one re-raises for reconnect.
        scripts = [
            {
                "frames": [_make_kline_frame() for _ in range(3)],
                "close_exc": ConnectionClosedError(None, None),
            },
            {
                "frames": [_make_kline_frame() for _ in range(3)],
                "close_exc": ConnectionClosedError(None, None),
            },
            {
                "frames": [_make_kline_frame() for _ in range(4)],
                "close_exc": ConnectionClosedError(None, None),
            },
        ]
        _patch_connect_scripts(monkeypatch, scripts)

        received: list = []
        async with BinanceWsClient(["solusdt@kline_1m"]) as ws:
            async def _collect() -> None:
                async for msg in ws.stream():
                    received.append(msg)
                    if len(received) >= 10:
                        return
            await asyncio.wait_for(_collect(), timeout=1.0)

        assert len(received) == 10
        assert all(m.kind is StreamKind.KLINE for m in received)

    @pytest.mark.asyncio
    async def test_reconnect_after_connection_closed(
        self, monkeypatch, no_jitter, sleep_calls
    ) -> None:
        """After ConnectionClosedError, client reconnects and continues delivering.

        Setup: first connection delivers 3 frames then is closed by the server
        with ConnectionClosedError; the second connection delivers 3 more frames
        then hangs (idle). The consumer collects all 6 frames before the test
        exits via async-with, which cancels the read-loop cleanly.

        Verifies:
          * len(received) == 6 (no message loss across the reconnect boundary)
          * call_count[0] >= 2 (at least two connect() invocations)
          * all messages are KLINE (stream type preserved)
        """
        from websockets.exceptions import ConnectionClosedError
        from hermes.exchanges.binance_contracts import StreamKind

        scripts = [
            {
                "frames": [_make_kline_frame() for _ in range(3)],
                "close_exc": ConnectionClosedError(None, None),
            },
            {
                "frames": [_make_kline_frame() for _ in range(3)],
                "hang_after_frames": True,
            },
        ]
        call_count = _patch_connect_scripts(monkeypatch, scripts)

        received: list = []
        async with BinanceWsClient(["solusdt@kline_1m"]) as ws:
            async def _collect() -> None:
                async for msg in ws.stream():
                    received.append(msg)
                    if len(received) >= 6:
                        return
            await asyncio.wait_for(_collect(), timeout=1.0)

        assert len(received) == 6, f"expected 6 messages, got {len(received)}"
        assert all(m.kind is StreamKind.KLINE for m in received)
        assert call_count[0] >= 2, f"expected >= 2 connect attempts, got {call_count[0]}"

    @pytest.mark.asyncio
    async def test_unknown_exception_triggers_reconnect(
        self, monkeypatch, no_jitter, sleep_calls
    ) -> None:
        """Non-websockets exceptions also trigger reconnect.

        The broad ``except Exception`` in ``_run_with_reconnect`` must catch
        anything that isn't ``CancelledError`` -- including arbitrary
        ``RuntimeError``s from buggy parsers, networking middleware, or other
        unexpected sources -- and trigger a backoff + reconnect just like a
        clean ``ConnectionClosedError`` would.

        Without this guarantee a single transient bug downstream could silently
        kill the stream forever.
        """
        from hermes.exchanges.binance_contracts import StreamKind

        scripts = [
            {
                "frames": [_make_kline_frame() for _ in range(3)],
                "close_exc": RuntimeError("simulated unexpected boom"),
            },
            {
                "frames": [_make_kline_frame() for _ in range(3)],
                "hang_after_frames": True,
            },
        ]
        call_count = _patch_connect_scripts(monkeypatch, scripts)

        received: list = []
        async with BinanceWsClient(["solusdt@kline_1m"]) as ws:
            async def _collect() -> None:
                async for msg in ws.stream():
                    received.append(msg)
                    if len(received) >= 6:
                        return
            await asyncio.wait_for(_collect(), timeout=1.0)

        assert len(received) == 6, f"expected 6 messages, got {len(received)}"
        assert all(m.kind is StreamKind.KLINE for m in received)
        assert call_count[0] >= 2, f"expected >= 2 connect attempts, got {call_count[0]}"

    @pytest.mark.asyncio
    async def test_reconnect_exponential_backoff(
        self, monkeypatch, no_jitter, sleep_calls
    ) -> None:
        """Backoff between reconnect attempts follows ``[0, 1, 2, 4, 8, ...]``.

        Five consecutive ``ConnectionClosedError`` connections force five
        reconnect attempts; the 6th connection hangs so the test can exit
        deterministically. With ``no_jitter`` patching ``random.uniform`` to
        zero, the resulting backoff sequence must be:

          attempt=1 -> 0  (always immediate)
          attempt=2 -> 1  (2**0)
          attempt=3 -> 2  (2**1)
          attempt=4 -> 4  (2**2)
          attempt=5 -> 8  (2**3)

        We filter ``sleep_calls`` to delays > 0 to ignore the many
        ``asyncio.sleep(0)`` cooperative yields from inside the read-loop
        and from the mock connection itself.
        """
        from websockets.exceptions import ConnectionClosedError

        scripts = [
            {
                "frames": [_make_kline_frame()],
                "close_exc": ConnectionClosedError(None, None),
            }
            for _ in range(5)
        ] + [
            {
                "frames": [_make_kline_frame()],
                "hang_after_frames": True,
            }
        ]
        call_count = _patch_connect_scripts(monkeypatch, scripts)

        received: list = []
        async with BinanceWsClient(["solusdt@kline_1m"]) as ws:
            async def _collect() -> None:
                async for msg in ws.stream():
                    received.append(msg)
                    if len(received) >= 6:
                        return
            await asyncio.wait_for(_collect(), timeout=1.0)

        # Filter to backoff sleeps (delay > 0); the mock + read-loop emit
        # many cooperative sleep(0)s that are noise here.
        backoff_delays = [d for d in sleep_calls if d > 0]
        assert backoff_delays[:4] == [1, 2, 4, 8], (
            f"expected backoff prefix [1, 2, 4, 8], got {backoff_delays[:4]}"
        )
        assert call_count[0] >= 6, (
            f"expected >= 6 connect attempts, got {call_count[0]}"
        )

    @pytest.mark.asyncio
    async def test_backoff_capped_at_60s(
        self, monkeypatch, no_jitter, sleep_calls
    ) -> None:
        """Backoff delay is capped at 60 seconds regardless of attempt count.

        Without a cap, exponential growth would yield 128s, 256s, 512s, ...,
        which would make recovery from extended outages absurdly slow. The
        implementation caps backoff at ``_MAX_BACKOFF_SECONDS = 60``.

        Setup: 10 consecutive ConnectionClosedError connections force
        attempts 1..10. The expected backoff sequence (with no_jitter):

          attempt=2 -> 1,  attempt=3 -> 2,  attempt=4 -> 4,  attempt=5 -> 8
          attempt=6 -> 16, attempt=7 -> 32, attempt=8 -> 60 (capped from 64)
          attempt=9 -> 60, attempt=10 -> 60
        """
        from websockets.exceptions import ConnectionClosedError

        scripts = [
            {
                "frames": [_make_kline_frame()],
                "close_exc": ConnectionClosedError(None, None),
            }
            for _ in range(10)
        ] + [
            {
                "frames": [_make_kline_frame()],
                "hang_after_frames": True,
            }
        ]
        call_count = _patch_connect_scripts(monkeypatch, scripts)

        received: list = []
        async with BinanceWsClient(["solusdt@kline_1m"]) as ws:
            async def _collect() -> None:
                async for msg in ws.stream():
                    received.append(msg)
                    if len(received) >= 11:
                        return
            await asyncio.wait_for(_collect(), timeout=2.0)

        backoff_delays = [d for d in sleep_calls if d > 0]
        assert max(backoff_delays) == 60, (
            f"expected max backoff == 60, got {max(backoff_delays)}; "
            f"full backoff sequence: {backoff_delays}"
        )
        # Also verify the cap is actually hit at least twice (attempts 8, 9, 10).
        assert backoff_delays.count(60) >= 2, (
            f"expected cap hit at least twice, got count={backoff_delays.count(60)}; "
            f"sequence: {backoff_delays}"
        )

    @pytest.mark.asyncio
    async def test_backoff_reset_after_success(
        self, monkeypatch, no_jitter, sleep_calls
    ) -> None:
        """Attempt counter resets to 0 after a clean server close.

        After a sustained healthy connection, a brief disconnect should NOT
        be treated as the continuation of an old failure chain. Otherwise a
        long-lived bot that has reconnected many times early in its life
        would face minute-long backoffs for any later transient blip --
        which is exactly when low latency matters most.

        Setup:
          script[0..1]: ClosedError x 2 -- attempt climbs to 2, backoff [1]
          script[2]   : 1 frame then clean ConnectionClosedOK -- _run_one
                        returns cleanly, attempt resets to 0
          script[3..4]: ClosedError x 2 -- attempt climbs to 2 AGAIN, the
                        backoff sequence restarts: another [1]
          script[5]   : hang, lets the test exit

        Expected backoff_delays (filtered to > 0): [1, 1], NOT [1, 2, 4].
        """
        from websockets.exceptions import ConnectionClosedError

        scripts = [
            # 2 failed connections
            {
                "frames": [_make_kline_frame()],
                "close_exc": ConnectionClosedError(None, None),
            },
            {
                "frames": [_make_kline_frame()],
                "close_exc": ConnectionClosedError(None, None),
            },
            # 1 healthy connection that ends cleanly (close_exc=None ->
            # mock raises StopAsyncIteration via the ConnectionClosedOK path,
            # which _run_one treats as a clean server close)
            {
                "frames": [_make_kline_frame()],
                "close_exc": None,
            },
            # 2 more failed connections after the healthy one
            {
                "frames": [_make_kline_frame()],
                "close_exc": ConnectionClosedError(None, None),
            },
            {
                "frames": [_make_kline_frame()],
                "close_exc": ConnectionClosedError(None, None),
            },
            # Hang so the test can exit deterministically
            {
                "frames": [_make_kline_frame()],
                "hang_after_frames": True,
            },
        ]
        call_count = _patch_connect_scripts(monkeypatch, scripts)

        received: list = []
        async with BinanceWsClient(["solusdt@kline_1m"]) as ws:
            async def _collect() -> None:
                async for msg in ws.stream():
                    received.append(msg)
                    if len(received) >= 6:
                        return
            await asyncio.wait_for(_collect(), timeout=2.0)

        backoff_delays = [d for d in sleep_calls if d > 0]
        assert backoff_delays == [1, 1], (
            f"expected backoff [1, 1] (reset after success), got {backoff_delays}"
        )
        assert call_count[0] >= 6, (
            f"expected >= 6 connect attempts, got {call_count[0]}"
        )

    @pytest.mark.asyncio
    async def test_cancelled_error_exits_cleanly(
        self, monkeypatch, no_jitter, sleep_calls
    ) -> None:
        """User-triggered cancellation exits without reconnecting.

        When the consumer leaves the ``async with`` block, ``__aexit__``
        cancels the read-loop task. ``_run_with_reconnect`` must:
          * propagate ``CancelledError`` (NOT treat it as a transient failure)
          * NOT trigger a reconnect attempt
          * NOT emit a backoff sleep

        Without this guarantee, calling ``.close()`` on a healthy client
        would race against an infinite reconnect loop, leaking tasks and
        possibly opening a new connection right before shutdown.

        Setup: one connection that delivers 1 frame then hangs forever.
        The consumer collects that 1 frame and immediately exits the
        async-with block, which should cancel the read-loop and unblock.
        """
        scripts = [
            {
                "frames": [_make_kline_frame()],
                "hang_after_frames": True,
            },
        ]
        call_count = _patch_connect_scripts(monkeypatch, scripts)

        received: list = []
        async with BinanceWsClient(["solusdt@kline_1m"]) as ws:
            async def _collect_one() -> None:
                async for msg in ws.stream():
                    received.append(msg)
                    return
            await asyncio.wait_for(_collect_one(), timeout=1.0)
        # Reaching this line means __aexit__ returned -- the cancel was clean.

        assert len(received) == 1, (
            f"expected 1 message before cancel, got {len(received)}"
        )
        assert call_count[0] == 1, (
            f"expected exactly 1 connect (no reconnect after cancel), "
            f"got {call_count[0]}"
        )
        # No backoff sleep should have been triggered: cancellation is not
        # a transient failure.
        backoff_delays = [d for d in sleep_calls if d > 0]
        assert backoff_delays == [], (
            f"expected no backoff sleeps on cancel, got {backoff_delays}"
        )
