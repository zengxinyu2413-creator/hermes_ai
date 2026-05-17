"""Binance WebSocket client for market data streams.

Phase 2.D — skeleton stage. This module defines the client surface
(parameter validation, URL resolution, async context-manager lifecycle)
but does NOT yet open a connection. Step 2.D.4 will wire the read loop
and message dispatch; Step 2.D.5 will add auto-reconnect.

User-data streams are intentionally out of scope here: Binance deprecated
the REST listenKey endpoints on 2026-02-04 (HTTP 410 Gone). User-data
support is deferred to Phase 5, when order execution requires it, at
which point we'll use the new WebSocket-API RPC (userDataStream.subscribe).
"""

from __future__ import annotations

import asyncio
import json
import random
import re
import time
import websockets
from typing import TYPE_CHECKING, Any

import structlog

from hermes.exchanges.binance_contracts import (
    BookTicker,
    Kline,
    StreamKind,
    StreamMessage,
    Trade,
    WsMetrics,
)
from hermes.exchanges.binance_credentials import BinanceEnvironment

if TYPE_CHECKING:
    pass


_logger = structlog.get_logger(__name__)


# Combined-stream WebSocket base URLs.
# Combined-stream format: <base>/stream?streams=<s1>/<s2>/...
# This gives us wrapped frames: {"stream": "<name>", "data": {...}}
# (vs. raw-stream which gives bare data frames — harder to demux).
_WS_BASE_URLS: dict[BinanceEnvironment, str] = {
    BinanceEnvironment.TESTNET: "wss://stream.testnet.binance.vision",
    BinanceEnvironment.MAINNET: "wss://stream.binance.com:9443",
}

# Hard cap on combined streams per connection. Binance allows up to 1024
# streams per connection; we cap lower to keep one connection focused and
# leave headroom for the strategy framework to open multiple clients.
_MAX_STREAMS_PER_CONNECTION = 200

# Binance stream-type part (after '@') accepts alphanumerics and underscore.
# Binance is case-sensitive in stream names: 'bookTicker' is NOT the same as 'bookticker'
# (the latter is silently ignored, no error returned). Symbol part (before '@')
# must still be lowercase per Binance docs.
_STREAM_TYPE_RE = re.compile(r"[a-zA-Z0-9_]+")

# Auto-reconnect parameters (Phase 2.D.5).
# Backoff cap of 60s aligns with what most production HFT clients use:
# fast enough to recover from short blips, slow enough to avoid hammering
# Binance during outages.
_MAX_BACKOFF_SECONDS = 60

# Binance closes connections at the 24h mark. We reconnect at 23h to avoid
# being kicked mid-frame and to spread reconnect load over time.
_MAX_CONNECTION_SECONDS = 23 * 3600

# WebSocket keepalive (Phase 2.D.6).
# The websockets library sends a ping every _WS_PING_INTERVAL seconds and
# closes the connection if no pong is received within _WS_PING_TIMEOUT.
# This catches half-open TCP connections (NAT timeout, route flap, etc.)
# faster than waiting on the OS TCP keepalive. A ConnectionClosed raised
# here propagates through _run_one into _run_with_reconnect's broad except
# and triggers backoff + reconnect.
_WS_PING_INTERVAL = 20
_WS_PING_TIMEOUT = 10


class BinanceWsClient:
    """Async client for Binance combined market-data WebSocket streams.

    Yields :class:`StreamMessage` envelopes to consumers via :meth:`stream`.

    The stream list is fixed at construction time; dynamic subscribe /
    unsubscribe is not supported in Phase 2.D. To change subscriptions,
    close this client and open a new one.

    Parameters
    ----------
    streams:
        Non-empty list of Binance stream names, e.g.
        ``["solusdt@kline_1m", "solusdt@bookTicker", "solusdt@trade"]``.
        Must be lowercase ASCII; validated at construction.
    env:
        Target environment. Defaults to TESTNET.
    queue_max_size:
        Bounded queue between the read loop and the consumer. When full,
        the read loop blocks — this provides backpressure rather than
        unbounded memory growth if a slow consumer falls behind. Default
        10_000 messages (~minutes of buffer at typical book-ticker rates).

    Notes
    -----
    Skeleton stage: construction validates and prepares state but does not
    open a connection. Step 2.D.4 will implement ``__aenter__`` /
    ``__aexit__`` and the read loop.
    """

    __slots__ = (
        "_streams",
        "_env",
        "_queue_max_size",
        "_queue",
        "_main_task",
        "_closed",
        "_messages_received_total",
        "_messages_by_kind",
        "_reconnect_count",
        "_current_attempt",
        "_last_message_at",
        "_connected_since",
        "_total_connect_duration_s",
    )

    def __init__(
        self,
        streams: list[str],
        *,
        env: BinanceEnvironment = BinanceEnvironment.TESTNET,
        queue_max_size: int = 10_000,
    ) -> None:
        self._streams = self._validate_streams(streams)
        self._env = env
        self._queue_max_size = self._validate_queue_size(queue_max_size)

        # Lazy-init: the queue is created on __aenter__ so it's bound to the
        # right event loop. Storing None here keeps construction loop-free,
        # which matters for tests that construct without an event loop.
        self._queue: asyncio.Queue[StreamMessage] | None = None
        self._main_task: asyncio.Task[None] | None = None
        self._closed: bool = False

        # Metrics counters — updated by _run_one and _run_with_reconnect.
        self._messages_received_total: int = 0
        self._messages_by_kind: dict[StreamKind, int] = {}
        self._reconnect_count: int = 0
        self._current_attempt: int = 0
        self._last_message_at: float | None = None
        self._connected_since: float | None = None
        self._total_connect_duration_s: float = 0.0

    # ------------------------------------------------------------------ #
    # Validation helpers                                                 #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _validate_streams(streams: list[str]) -> tuple[str, ...]:
        if not isinstance(streams, list):
            raise TypeError(
                f"streams must be a list, got {type(streams).__name__}"
            )
        if not streams:
            raise ValueError("streams must not be empty")
        if len(streams) > _MAX_STREAMS_PER_CONNECTION:
            raise ValueError(
                f"streams length {len(streams)} exceeds cap "
                f"{_MAX_STREAMS_PER_CONNECTION}; open multiple clients instead"
            )

        seen: set[str] = set()
        for s in streams:
            if not isinstance(s, str):
                raise TypeError(
                    f"stream entries must be str, got {type(s).__name__}"
                )
            if not s:
                raise ValueError("stream entries must be non-empty")
            if "@" not in s:
                raise ValueError(
                    f"stream {s!r} must contain '@' "
                    "(format: <symbol>@<stream-type>)"
                )
            symbol_part, _, type_part = s.partition("@")
            if "@" in type_part:
                raise ValueError(
                    f"stream {s!r} must contain exactly one '@'"
                )
            if symbol_part != symbol_part.lower():
                raise ValueError(
                    f"stream {s!r} symbol part {symbol_part!r} "
                    "must be lowercase (Binance requirement)"
                )
            if not _STREAM_TYPE_RE.fullmatch(type_part):
                raise ValueError(
                    f"stream {s!r} stream-type part {type_part!r} "
                    "must match [a-zA-Z0-9_]+"
                )
            if s in seen:
                raise ValueError(f"duplicate stream: {s!r}")
            seen.add(s)

        return tuple(streams)

    @staticmethod
    def _validate_queue_size(size: int) -> int:
        if not isinstance(size, int) or isinstance(size, bool):
            raise TypeError(
                f"queue_max_size must be int, got {type(size).__name__}"
            )
        if size < 1:
            raise ValueError(
                f"queue_max_size must be >= 1, got {size}"
            )
        return size

    @staticmethod
    def _compute_backoff_delay(attempt: int) -> float:
        """Exponential backoff with +/-25% jitter, capped at 60s.

        attempt 1 -> 0s  (immediate retry; transient blips often recover)
        attempt 2 -> ~1s
        attempt 3 -> ~2s
        attempt N -> min(2^(N-2), 60) seconds, with +/-25% jitter applied

        Jitter prevents reconnect storms when many clients are kicked
        simultaneously (e.g. during a Binance maintenance window).

        Returns 0.0 for attempt <= 1; non-negative float otherwise.
        """
        if attempt <= 1:
            return 0.0
        base = min(2 ** (attempt - 2), _MAX_BACKOFF_SECONDS)
        jitter = random.uniform(-0.25, 0.25) * base
        return max(0.0, base + jitter)

    # ------------------------------------------------------------------ #
    # Public read-only accessors                                         #
    # ------------------------------------------------------------------ #

    @property
    def streams(self) -> tuple[str, ...]:
        """Immutable tuple of subscribed stream names."""
        return self._streams

    @property
    def env(self) -> BinanceEnvironment:
        return self._env

    @property
    def url(self) -> str:
        """Fully-resolved combined-stream URL for this client."""
        base = _WS_BASE_URLS[self._env]
        joined = "/".join(self._streams)
        return f"{base}/stream?streams={joined}"

    @property
    def is_running(self) -> bool:
        """True if the read loop task is alive."""
        return self._main_task is not None and not self._main_task.done()

    @property
    def metrics(self) -> WsMetrics:
        """Point-in-time snapshot of counters. Safe to call from any coroutine."""
        return WsMetrics(
            messages_received_total=self._messages_received_total,
            messages_by_kind=dict(self._messages_by_kind),
            reconnect_count=self._reconnect_count,
            current_attempt=self._current_attempt,
            last_message_at=self._last_message_at,
            connected_since=self._connected_since,
            total_connect_duration_s=self._total_connect_duration_s,
        )

    # ------------------------------------------------------------------ #
    # Repr                                                               #
    # ------------------------------------------------------------------ #

    def __repr__(self) -> str:
        return (
            f"BinanceWsClient(env={self._env.value}, "
            f"streams={len(self._streams)}, "
            f"running={self.is_running})"
        )

    # ------------------------------------------------------------------ #
    # Message parsing (Phase 2.D.4a — pure functions, never raise)        #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _classify_stream(stream: str) -> StreamKind:
        """Map a Binance combined-stream name to a :class:`StreamKind`.

        Stream format: ``<symbol>@<type>[_<param>]``. Examples::

            solusdt@kline_1m   -> KLINE
            solusdt@bookTicker -> BOOK_TICKER  (Binance returns "bookticker")
            solusdt@trade      -> TRADE
            solusdt@depth20    -> UNKNOWN  (not supported in Phase 2.D)

        Binance normalizes returned stream names to lowercase even when the
        subscription used camelCase, so we lowercase the suffix before matching.
        """
        if "@" not in stream:
            return StreamKind.UNKNOWN
        suffix = stream.split("@", 1)[1].lower()
        if suffix.startswith("kline_"):
            return StreamKind.KLINE
        if suffix == "bookticker":
            return StreamKind.BOOK_TICKER
        if suffix == "trade":
            return StreamKind.TRADE
        return StreamKind.UNKNOWN

    @staticmethod
    def _parse_message(raw: str) -> StreamMessage:
        """Translate one raw combined-stream frame into a StreamMessage.

        Never raises. Malformed or unrecognized frames produce
        ``StreamMessage(kind=UNKNOWN)`` so the read loop survives bad data.
        Diagnostic detail goes to structlog (``reason``, ``stream``,
        ``raw_preview``) rather than the envelope, keeping the consumer API
        narrow.

        Expected envelope shape (Binance combined-stream)::

            {"stream": "<name>", "data": { ...inner event... }}
        """
        # ---- Step 1: JSON decode ----
        try:
            envelope: Any = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            _logger.warning(
                "ws_parse_failed",
                reason="invalid_json",
                error=str(exc),
                raw_preview=raw[:120] if isinstance(raw, str) else repr(raw)[:120],
            )
            return StreamMessage(
                kind=StreamKind.UNKNOWN,
                received_at_ms=StreamMessage.now_ms(),
                stream="",
                raw={},
            )

        if not isinstance(envelope, dict):
            _logger.warning(
                "ws_parse_failed",
                reason="envelope_not_object",
                envelope_type=type(envelope).__name__,
            )
            return StreamMessage(
                kind=StreamKind.UNKNOWN,
                received_at_ms=StreamMessage.now_ms(),
                stream="",
                raw={},
            )

        # ---- Step 2: required envelope fields ----
        stream = envelope.get("stream")
        data = envelope.get("data")

        if not isinstance(stream, str) or not stream:
            _logger.warning(
                "ws_parse_failed",
                reason="missing_stream",
                envelope_keys=list(envelope.keys()),
            )
            return StreamMessage(
                kind=StreamKind.UNKNOWN,
                received_at_ms=StreamMessage.now_ms(),
                stream="",
                raw=envelope,
            )

        if not isinstance(data, dict):
            _logger.warning(
                "ws_parse_failed",
                reason="missing_data",
                stream=stream,
            )
            return StreamMessage(
                kind=StreamKind.UNKNOWN,
                received_at_ms=StreamMessage.now_ms(),
                stream=stream,
                raw=envelope,
            )

        # ---- Step 3: classify stream type ----
        kind = BinanceWsClient._classify_stream(stream)
        if kind is StreamKind.UNKNOWN:
            _logger.info(
                "ws_unknown_stream_type",
                stream=stream,
            )
            return StreamMessage(
                kind=StreamKind.UNKNOWN,
                received_at_ms=StreamMessage.now_ms(),
                stream=stream,
                raw=envelope,
            )

        # ---- Step 4: parse inner payload by kind ----
        received_at_ms = StreamMessage.now_ms()
        try:
            if kind is StreamKind.KLINE:
                # Inner Binance kline event: {"e": "kline", "s": "SOLUSDT", "k": {...}}
                inner_symbol = data.get("s")
                if not isinstance(inner_symbol, str):
                    raise ValueError("kline event missing 's' (symbol)")
                k_payload = data.get("k")
                if not isinstance(k_payload, dict):
                    raise ValueError("kline event missing 'k' (kline payload)")
                # Interval from the stream name; split on "@kline_" to handle
                # multi-char intervals (1m, 15m, 1h, 1d) unambiguously.
                interval = stream.split("@kline_", 1)[1]
                kline = Kline.from_binance_ws_payload(
                    k_payload,
                    symbol=inner_symbol,
                    interval=interval,
                )
                return StreamMessage(
                    kind=StreamKind.KLINE,
                    received_at_ms=received_at_ms,
                    stream=stream,
                    kline=kline,
                    raw=envelope,
                )

            if kind is StreamKind.BOOK_TICKER:
                book_ticker = BookTicker.from_binance_ws_payload(
                    data,
                    received_at_ms=received_at_ms,
                )
                return StreamMessage(
                    kind=StreamKind.BOOK_TICKER,
                    received_at_ms=received_at_ms,
                    stream=stream,
                    book_ticker=book_ticker,
                    raw=envelope,
                )

            if kind is StreamKind.TRADE:
                trade = Trade.from_binance_ws_payload(data)
                return StreamMessage(
                    kind=StreamKind.TRADE,
                    received_at_ms=received_at_ms,
                    stream=stream,
                    trade=trade,
                    raw=envelope,
                )

            # Defensive: _classify_stream returned a kind we don't handle here.
            raise ValueError(f"unhandled kind: {kind}")

        except (ValueError, KeyError, TypeError) as exc:
            _logger.warning(
                "ws_parse_failed",
                reason="payload_parse_error",
                stream=stream,
                kind=kind.value,
                error=str(exc),
            )
            return StreamMessage(
                kind=StreamKind.UNKNOWN,
                received_at_ms=received_at_ms,
                stream=stream,
                raw=envelope,
            )

    # ------------------------------------------------------------------ #
    # Async lifecycle (Phase 2.D.4b - single-connection, no reconnect)   #
    # ------------------------------------------------------------------ #
    #
    # Reconnect logic lands in Step 2.D.5. For now, a single underlying
    # websockets.connect() is opened on __aenter__; if it terminates
    # (cleanly or with an error), the read loop ends and stream() drains
    # whatever is left in the queue before returning.

    async def __aenter__(self) -> "BinanceWsClient":
        if self._closed:
            raise RuntimeError(
                "BinanceWsClient cannot be reused after close; "
                "construct a new instance"
            )
        if self._main_task is not None:
            raise RuntimeError(
                "BinanceWsClient is already entered; nesting is not supported"
            )
        # Queue is bound to the current event loop here, not at construction.
        self._queue = asyncio.Queue(maxsize=self._queue_max_size)
        self._main_task = asyncio.create_task(
            self._run_with_reconnect(), name=f"binance_ws_run[{self._env.value}]"
        )
        _logger.info(
            "ws_client_entered",
            env=self._env.value,
            streams=len(self._streams),
        )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self._closed = True
        if self._main_task is not None and not self._main_task.done():
            self._main_task.cancel()
            try:
                await self._main_task
            except asyncio.CancelledError:
                pass
            except Exception as cleanup_exc:  # noqa: BLE001 - log and swallow
                # We are in the exit path; surfacing this would mask the
                # original exception (if any). Log and move on.
                _logger.warning(
                    "ws_cleanup_error",
                    error=str(cleanup_exc),
                    error_type=type(cleanup_exc).__name__,
                )
        _logger.info("ws_client_exited", env=self._env.value)

    async def _run_with_reconnect(self) -> None:
        """Supervise WebSocket lifecycle with auto-reconnect.

        Wraps _run_one in an infinite reconnect loop with exponential
        backoff and jitter. Never gives up on errors (suits 24/7 quant
        operations); the only way out is .close() triggering a
        CancelledError.

        Each connection is also capped at 23h to proactively reconnect
        before Binance's 24h server-side limit kicks in.
        """
        attempt = 0
        while True:
            try:
                await asyncio.wait_for(
                    self._run_one(),
                    timeout=_MAX_CONNECTION_SECONDS,
                )
                # _run_one returned cleanly: server closed connection.
                # Reset attempt and reconnect immediately.
                _logger.info("ws_connection_closed_by_server")
                attempt = 0
                self._current_attempt = 0
            except asyncio.TimeoutError:
                # 23h cap hit: proactive reconnect. Not a failure.
                _logger.info("ws_proactive_reconnect_23h")
                attempt = 0
                self._current_attempt = 0
            except asyncio.CancelledError:
                # User .close() triggered cancellation. Exit cleanly.
                raise
            except Exception:
                # Any other error (ConnectionClosed, OSError, ...):
                # log with traceback and back off before retrying.
                _logger.warning(
                    "ws_connection_error",
                    attempt=attempt + 1,
                    exc_info=True,
                )
                attempt += 1
                self._reconnect_count += 1
                self._current_attempt = attempt

            if attempt > 0:
                delay = self._compute_backoff_delay(attempt)
                _logger.info(
                    "ws_reconnect_scheduled",
                    attempt=attempt,
                    delay_seconds=round(delay, 2),
                )
                await asyncio.sleep(delay)

    async def _run_one(self) -> None:
        """Single-connection read loop.

        Connects once, iterates frames, parses each into a StreamMessage,
        and pushes to the queue. Terminates on:
          * clean server close (StopAsyncIteration from the iterator)
          * any websockets exception (logged, then re-raised for
          ``_run_with_reconnect`` to backoff and reconnect)
          * external task.cancel() (propagates as CancelledError - re-raised)

        ``_parse_message`` is guaranteed not to raise, so a single outer
        try/except is sufficient. The queue is bounded; ``await put`` blocks
        if the consumer falls behind, applying backpressure to the socket.
        """
        assert self._queue is not None  # set in __aenter__
        try:
            async with websockets.connect(
                self.url,
                ping_interval=_WS_PING_INTERVAL,
                ping_timeout=_WS_PING_TIMEOUT,
            ) as ws:
                self._connected_since = time.monotonic()
                _logger.info("ws_connected", url=self.url)
                try:
                    async for raw in ws:
                        # raw can be str or bytes depending on the frame type.
                        # Binance always sends text JSON for market-data streams,
                        # but be defensive in case of unexpected binary frames.
                        if isinstance(raw, bytes):
                            try:
                                raw = raw.decode("utf-8")
                            except UnicodeDecodeError:
                                _logger.warning("ws_binary_frame_skipped")
                                continue
                        self._messages_received_total += 1
                        self._last_message_at = time.monotonic()
                        msg = self._parse_message(raw)
                        self._messages_by_kind[msg.kind] = self._messages_by_kind.get(msg.kind, 0) + 1
                        await self._queue.put(msg)
                finally:
                    if self._connected_since is not None:
                        self._total_connect_duration_s += time.monotonic() - self._connected_since
                        self._connected_since = None
        except asyncio.CancelledError:
            _logger.info("ws_run_cancelled")
            raise
        except Exception as exc:  # noqa: BLE001 - log + re-raise for reconnect
            # Anything else (connection refused, ConnectionClosedError,
            # OSError, etc.) terminates this run. Re-raise so
            # _run_with_reconnect can backoff and reconnect.
            # CancelledError is handled separately above.
            _logger.warning(
                "ws_run_terminated",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            raise

    async def stream(self):
        """Async-iterate over :class:`StreamMessage` envelopes.

        Usage::

            async with BinanceWsClient([...]) as ws:
                async for msg in ws.stream():
                    if msg.kind is StreamKind.KLINE:
                        ...

        Behaviour when the underlying connection ends:

        1. The read loop task finishes (cleanly or with logged error).
        2. ``stream()`` drains any messages still in the queue.
        3. After the queue is empty, ``stream()`` returns (the async-for
           in the consumer exits cleanly without raising).

        This guarantees zero message loss at the boundary between
        connection-end and consumer-exit: messages successfully parsed
        and queued before disconnection are always delivered.
        """
        if self._queue is None or self._main_task is None:
            raise RuntimeError(
                "stream() can only be called inside `async with`"
            )

        queue = self._queue
        task = self._main_task

        while True:
            # If the read-loop task is still running, race a queue.get()
            # against task completion so we wake up either on a new message
            # or when the connection ends.
            if not task.done():
                get_task = asyncio.create_task(queue.get())
                try:
                    done, _pending = await asyncio.wait(
                        {get_task, task},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                except asyncio.CancelledError:
                    # Consumer was cancelled; tidy up our helper task.
                    get_task.cancel()
                    raise

                if get_task in done:
                    yield get_task.result()
                    continue

                # The read loop finished while we were waiting. Don't lose
                # the get_task - its future may already have a value pulled
                # from the queue (race window). If it does, yield it.
                if get_task.done() and not get_task.cancelled():
                    try:
                        yield get_task.result()
                    except BaseException:  # noqa: BLE001 - defensive
                        pass
                else:
                    get_task.cancel()
                # Fall through to drain.

            # Read loop is done. Drain anything remaining in the queue
            # without blocking, then return.
            while not queue.empty():
                yield queue.get_nowait()
            return
