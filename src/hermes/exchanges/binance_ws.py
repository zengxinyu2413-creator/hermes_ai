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
from typing import TYPE_CHECKING

from hermes.exchanges.binance_credentials import BinanceEnvironment

if TYPE_CHECKING:
    from hermes.exchanges.binance_contracts import StreamMessage


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
            if s != s.lower():
                raise ValueError(
                    f"stream {s!r} must be lowercase (Binance requirement)"
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
    # Async lifecycle (skeleton — wired in Step 2.D.4)                   #
    # ------------------------------------------------------------------ #

    async def __aenter__(self) -> BinanceWsClient:
        if self._closed:
            raise RuntimeError(
                "BinanceWsClient cannot be reused after close; "
                "construct a new instance"
            )
        # Step 2.D.4 will: create self._queue, start read-loop task,
        # await first successful connection.
        raise NotImplementedError(
            "BinanceWsClient connection logic lands in Step 2.D.4"
        )

    async def __aexit__(self, exc_type, exc, tb) -> None:
        # Step 2.D.4 will: cancel self._main_task, close websocket,
        # drain queue, set self._closed = True.
        raise NotImplementedError(
            "BinanceWsClient shutdown logic lands in Step 2.D.4"
        )

    async def stream(self):
        """Async-iterate over :class:`StreamMessage` envelopes.

        Wired in Step 2.D.4. The shape will be::

            async with BinanceWsClient([...]) as ws:
                async for msg in ws.stream():
                    if msg.kind is StreamKind.KLINE:
                        ...
        """
        raise NotImplementedError(
            "BinanceWsClient.stream lands in Step 2.D.4"
        )