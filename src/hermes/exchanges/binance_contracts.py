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

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


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
        every digit Binance sends.
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
        )