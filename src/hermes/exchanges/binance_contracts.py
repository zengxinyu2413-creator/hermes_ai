"""Typed data contracts for Binance market data.

Strategies and persistence layers consume these objects — they never touch
raw Binance JSON. This keeps the rest of the codebase decoupled from the
exchange's response format and lets us swap in OKX / Bybit / etc. later by
producing the same types.

All prices and volumes use Decimal, not float. Float arithmetic on prices
produces silent rounding errors that compound in PnL math; Decimal is slower
but accurate. The performance cost is irrelevant at our trade frequency.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any


class KlineInterval(str, Enum):
    """Binance-supported kline intervals.

    See: https://binance-docs.github.io/apidocs/spot/en/#kline-candlestick-data
    Enum value is the literal string Binance expects on the wire.
    """

    SEC_1 = "1s"

    MIN_1 = "1m"
    MIN_3 = "3m"
    MIN_5 = "5m"
    MIN_15 = "15m"
    MIN_30 = "30m"

    HOUR_1 = "1h"
    HOUR_2 = "2h"
    HOUR_4 = "4h"
    HOUR_6 = "6h"
    HOUR_8 = "8h"
    HOUR_12 = "12h"

    DAY_1 = "1d"
    DAY_3 = "3d"

    WEEK_1 = "1w"
    MONTH_1 = "1M"


@dataclass(frozen=True, slots=True)
class Kline:
    """A single candlestick bar.

    Frozen + slots: immutable and memory-efficient (we'll have millions of
    these during backtests). Equality and hashability work out of the box,
    which is useful when deduping bars during gap recovery.

    Fields are named exactly after the Binance schema for traceability.

    `is_closed` distinguishes:
      - True  -> bar is finalized (REST historical data, or WS bar with x=true)
      - False -> bar is still updating (WS in-progress bar)
    Strategies should typically only act on closed bars to avoid look-ahead
    bias. The default is True so all existing REST-derived Klines remain valid.
    """

    # Identity / time
    symbol: str                  # e.g. "SOLUSDT"
    interval: KlineInterval      # e.g. KlineInterval.MIN_1
    open_time_ms: int            # Unix ms at bar open
    close_time_ms: int           # Unix ms at bar close (exclusive of next bar)

    # OHLCV — Decimal, not float
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal              # base-asset volume (e.g. SOL)
    quote_volume: Decimal        # quote-asset volume (e.g. USDT)

    # Extras Binance includes
    trades: int                  # number of trades in this bar
    taker_buy_base_volume: Decimal   # volume from market BUYs (taker side)
    taker_buy_quote_volume: Decimal

    # Closed flag — default True so REST callers are unchanged.
    is_closed: bool = True

    @classmethod
    def from_binance_row(
        cls,
        row: list,
        *,
        symbol: str,
        interval: KlineInterval,
    ) -> "Kline":
        """Build a Kline from one row of Binance /api/v3/klines response.

        Binance returns each kline as a 12-element array:
            [
                0: openTime (ms),
                1: open (str),
                2: high (str),
                3: low (str),
                4: close (str),
                5: volume (str),
                6: closeTime (ms),
                7: quoteAssetVolume (str),
                8: numberOfTrades (int),
                9: takerBuyBaseAssetVolume (str),
                10: takerBuyQuoteAssetVolume (str),
                11: ignored,
            ]

        We pass strings through Decimal() directly (NOT float), preserving
        every digit Binance sends. REST historical bars are always closed,
        so is_closed defaults to True.
        """
        if len(row) < 11:
            raise ValueError(
                f"expected at least 11 fields in kline row, got {len(row)}"
            )
        return cls(
            symbol=symbol,
            interval=interval,
            open_time_ms=int(row[0]),
            open=Decimal(row[1]),
            high=Decimal(row[2]),
            low=Decimal(row[3]),
            close=Decimal(row[4]),
            volume=Decimal(row[5]),
            close_time_ms=int(row[6]),
            quote_volume=Decimal(row[7]),
            trades=int(row[8]),
            taker_buy_base_volume=Decimal(row[9]),
            taker_buy_quote_volume=Decimal(row[10]),
            # is_closed defaults True
        )

    @classmethod
    def from_binance_ws_payload(
        cls,
        payload: dict,
        *,
        symbol: str,
        interval: KlineInterval,
    ) -> "Kline":
        """Build a Kline from a Binance WS kline event's inner 'k' object.

        Binance pushes kline updates as:
            {
                "e": "kline",
                "E": 123456789,        # event time ms
                "s": "SOLUSDT",
                "k": {
                    "t": 123400000,    # kline start time
                    "T": 123459999,    # kline close time
                    "s": "SOLUSDT",
                    "i": "1m",
                    "o": "0.0010",
                    "c": "0.0020",
                    "h": "0.0025",
                    "l": "0.0015",
                    "v": "1000",       # volume (base)
                    "n": 100,          # number of trades
                    "x": false,        # is_closed
                    "q": "1.0000",     # quote volume
                    "V": "500",        # taker buy base volume
                    "Q": "0.500",      # taker buy quote volume
                    "B": "0"           # ignored
                }
            }

        This method accepts the inner 'k' dict (the WS client unwraps before
        calling), not the outer event. symbol and interval are passed in
        explicitly because the WS client already knows them from the stream
        name — relying on the payload's 's' and 'i' would couple our types
        to Binance's field naming.
        """
        try:
            return cls(
                symbol=symbol,
                interval=interval,
                open_time_ms=int(payload["t"]),
                close_time_ms=int(payload["T"]),
                open=Decimal(payload["o"]),
                high=Decimal(payload["h"]),
                low=Decimal(payload["l"]),
                close=Decimal(payload["c"]),
                volume=Decimal(payload["v"]),
                quote_volume=Decimal(payload["q"]),
                trades=int(payload["n"]),
                taker_buy_base_volume=Decimal(payload["V"]),
                taker_buy_quote_volume=Decimal(payload["Q"]),
                is_closed=bool(payload["x"]),
            )
        except KeyError as e:
            raise ValueError(
                f"missing required field {e!r} in Binance WS kline payload"
            ) from e


# ---------------------------------------------------------------------------
# WebSocket stream envelope types
# ---------------------------------------------------------------------------


class StreamKind(str, Enum):
    """High-level classification of a WebSocket message.

    Consumers branch on this to know which typed payload field to read on
    StreamMessage. UNKNOWN is a fallback — we never raise on unrecognized
    streams, we wrap them so the consumer can decide.
    """

    KLINE = "kline"
    BOOK_TICKER = "bookTicker"
    TRADE = "trade"
    USER_DATA = "userData"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class BookTicker:
    """Best bid/ask snapshot for a symbol.

    Binance's bookTicker stream pushes whenever the top of book changes for
    the subscribed symbol. The payload does NOT carry a Binance timestamp,
    so we stamp local receive time at parse — useful for latency analysis
    and for ordering events deterministically downstream.
    """

    symbol: str
    bid_price: Decimal
    bid_qty: Decimal
    ask_price: Decimal
    ask_qty: Decimal
    received_at_ms: int  # local receive time stamped by the WS client

    @classmethod
    def from_binance_ws_payload(
        cls,
        payload: dict,
        *,
        received_at_ms: int,
    ) -> "BookTicker":
        """Parse a Binance bookTicker payload.

            {
                "u": 400900217,    # order book updateId (we ignore)
                "s": "BNBUSDT",
                "b": "25.35190000",
                "B": "31.21000000",
                "a": "25.36520000",
                "A": "40.66000000"
            }
        """
        try:
            return cls(
                symbol=str(payload["s"]).upper(),
                bid_price=Decimal(payload["b"]),
                bid_qty=Decimal(payload["B"]),
                ask_price=Decimal(payload["a"]),
                ask_qty=Decimal(payload["A"]),
                received_at_ms=received_at_ms,
            )
        except KeyError as e:
            raise ValueError(
                f"missing required field {e!r} in Binance bookTicker payload"
            ) from e


@dataclass(frozen=True, slots=True)
class Trade:
    """A single executed trade on the public tape.

    `is_buyer_maker=True` means the BUY side was the resting (maker) order,
    i.e. the trade was initiated by a market SELL. This is Binance's
    convention and the opposite of some other exchanges, so we keep the
    flag explicit rather than renaming to e.g. "taker_side".
    """

    symbol: str
    trade_id: int
    price: Decimal
    qty: Decimal
    time_ms: int             # Binance trade time
    is_buyer_maker: bool     # True => taker was SELL

    @classmethod
    def from_binance_ws_payload(cls, payload: dict) -> "Trade":
        """Parse a Binance trade payload.

            {
                "e": "trade",
                "E": 123456789,
                "s": "BNBBTC",
                "t": 12345,        # trade id
                "p": "0.001",      # price
                "q": "100",        # quantity
                "T": 123456785,    # trade time
                "m": true,         # is buyer the market maker?
                "M": true          # ignore
            }
        """
        try:
            return cls(
                symbol=str(payload["s"]).upper(),
                trade_id=int(payload["t"]),
                price=Decimal(payload["p"]),
                qty=Decimal(payload["q"]),
                time_ms=int(payload["T"]),
                is_buyer_maker=bool(payload["m"]),
            )
        except KeyError as e:
            raise ValueError(
                f"missing required field {e!r} in Binance trade payload"
            ) from e


@dataclass(frozen=True, slots=True)
class StreamMessage:
    """Unified envelope yielded by BinanceWsClient.stream().

    Exactly one of (kline, book_ticker, trade) is populated for typed
    streams. For USER_DATA and UNKNOWN, the typed fields are None and `raw`
    carries the original payload dict — we don't model user data events yet
    (they have a large, evolving schema; we'll add typed wrappers in Phase 5
    when wiring order execution).

    `received_at_ms` is the WS client's local timestamp at parse time. It
    enables end-to-end latency measurement: e.g. for kline messages we can
    compare it against kline.close_time_ms to track how stale our data is.
    """

    kind: StreamKind
    received_at_ms: int
    stream: str                       # original stream name e.g. "solusdt@kline_1m"

    kline: Kline | None = None
    book_ticker: BookTicker | None = None
    trade: Trade | None = None
    raw: dict[str, Any] | None = None

    @staticmethod
    def now_ms() -> int:
        """Current local time in Unix ms. Exposed so tests can monkeypatch."""
        return int(time.time() * 1000)


@dataclass(frozen=True, slots=True)
class WsMetrics:
    """Point-in-time snapshot of BinanceWsClient internal counters.

    Returned by BinanceWsClient.metrics. All timestamp fields use
    time.monotonic() — comparable within a process but not across restarts.
    messages_by_kind is a shallow copy of the internal counter dict; mutating
    it does not affect the client.
    """

    messages_received_total: int
    messages_by_kind: dict[StreamKind, int]
    reconnect_count: int
    current_attempt: int
    last_message_at: float | None    # monotonic; None until first message
    connected_since: float | None    # monotonic; None when not connected
    total_connect_duration_s: float