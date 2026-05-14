"""Critical regression tests for binance_contracts.py.

Deliberately minimal — covers only the contracts that downstream WS client
code will depend on. Field-by-field validation is implicitly covered by
from_binance_row / from_binance_ws_payload tests.
"""
from decimal import Decimal

import pytest

from hermes.exchanges.binance_contracts import (
    BookTicker,
    Kline,
    KlineInterval,
    StreamKind,
    StreamMessage,
    Trade,
)


# ---------------------------------------------------------------------------
# Kline.is_closed default + REST regression
# ---------------------------------------------------------------------------


class TestKlineIsClosedDefault:
    def test_direct_construction_defaults_is_closed_true(self):
        """REST callers never pass is_closed; default must be True."""
        k = Kline(
            symbol="SOLUSDT",
            interval=KlineInterval.MIN_1,
            open_time_ms=1, close_time_ms=2,
            open=Decimal("1"), high=Decimal("1"),
            low=Decimal("1"), close=Decimal("1"),
            volume=Decimal("1"), quote_volume=Decimal("1"),
            trades=1,
            taker_buy_base_volume=Decimal("1"),
            taker_buy_quote_volume=Decimal("1"),
        )
        assert k.is_closed is True

    def test_from_binance_row_yields_closed_bar(self):
        """REST historical bars are always closed — Phase 2.B regression."""
        row = [
            1000, "100.5", "101.0", "100.0", "100.8",
            "50", 1999, "5040", 10, "20", "2016", "ignored",
        ]
        k = Kline.from_binance_row(
            row, symbol="SOLUSDT", interval=KlineInterval.MIN_1,
        )
        assert k.is_closed is True
        # Spot-check one Decimal field to catch wholesale regression
        assert k.close == Decimal("100.8")


# ---------------------------------------------------------------------------
# Kline.from_binance_ws_payload
# ---------------------------------------------------------------------------


def _valid_ws_kline_payload(*, x: bool = False) -> dict:
    """Minimal Binance WS kline inner 'k' payload."""
    return {
        "t": 1000, "T": 1999,
        "o": "100.5", "h": "101.0", "l": "100.0", "c": "100.8",
        "v": "50", "q": "5040",
        "n": 10,
        "V": "20", "Q": "2016",
        "x": x,
    }


class TestKlineFromWsPayload:
    def test_in_progress_bar_is_not_closed(self):
        k = Kline.from_binance_ws_payload(
            _valid_ws_kline_payload(x=False),
            symbol="SOLUSDT", interval=KlineInterval.MIN_1,
        )
        assert k.is_closed is False
        # Confirm fields decoded correctly so x=False doesn't mask other bugs
        assert k.close == Decimal("100.8")
        assert k.trades == 10

    def test_closed_bar_is_closed(self):
        k = Kline.from_binance_ws_payload(
            _valid_ws_kline_payload(x=True),
            symbol="SOLUSDT", interval=KlineInterval.MIN_1,
        )
        assert k.is_closed is True

    def test_missing_field_raises_value_error(self):
        bad = _valid_ws_kline_payload()
        del bad["c"]  # missing close price
        with pytest.raises(ValueError, match="missing required field"):
            Kline.from_binance_ws_payload(
                bad, symbol="SOLUSDT", interval=KlineInterval.MIN_1,
            )


# ---------------------------------------------------------------------------
# BookTicker
# ---------------------------------------------------------------------------


class TestBookTicker:
    def test_parse_uppercases_symbol_and_preserves_decimals(self):
        """Binance sometimes sends lowercase symbols in stream payloads;
        we normalize on parse so downstream consumers can rely on uppercase.
        """
        bt = BookTicker.from_binance_ws_payload(
            {
                "u": 12345, "s": "solusdt",
                "b": "100.12345678", "B": "5.0",
                "a": "100.12345679", "A": "10.0",
            },
            received_at_ms=999,
        )
        assert bt.symbol == "SOLUSDT"
        # Decimal precision must survive (string with 8 dp)
        assert bt.bid_price == Decimal("100.12345678")
        assert bt.ask_price == Decimal("100.12345679")
        assert bt.received_at_ms == 999

    def test_missing_field_raises_value_error(self):
        with pytest.raises(ValueError, match="missing required field"):
            BookTicker.from_binance_ws_payload(
                {"s": "SOLUSDT", "b": "100", "B": "5"},  # missing a / A
                received_at_ms=0,
            )


# ---------------------------------------------------------------------------
# Trade
# ---------------------------------------------------------------------------


class TestTrade:
    def test_is_buyer_maker_true_means_taker_was_seller(self):
        """Binance: m=true => buyer is maker => taker is the seller (market SELL).
        We preserve the flag verbatim to avoid renaming confusion.
        """
        t = Trade.from_binance_ws_payload({
            "e": "trade", "E": 1, "s": "solusdt",
            "t": 99, "p": "100.5", "q": "1.5", "T": 2,
            "m": True, "M": True,
        })
        assert t.symbol == "SOLUSDT"
        assert t.is_buyer_maker is True
        assert t.trade_id == 99
        assert t.price == Decimal("100.5")

    def test_is_buyer_maker_false_means_taker_was_buyer(self):
        t = Trade.from_binance_ws_payload({
            "e": "trade", "E": 1, "s": "SOLUSDT",
            "t": 100, "p": "100", "q": "1", "T": 2,
            "m": False, "M": True,
        })
        assert t.is_buyer_maker is False


# ---------------------------------------------------------------------------
# StreamKind + StreamMessage envelope
# ---------------------------------------------------------------------------


class TestStreamEnvelope:
    def test_stream_kind_has_all_expected_values(self):
        """Adding/removing a StreamKind affects all WS parsing logic; lock it."""
        values = {k.value for k in StreamKind}
        assert values == {
            "kline", "bookTicker", "trade", "userData", "unknown",
        }

    def test_stream_message_typed_fields_default_none(self):
        """Consumers branch on kind; non-matching typed fields must be None."""
        msg = StreamMessage(
            kind=StreamKind.UNKNOWN, received_at_ms=0, stream="x",
        )
        assert msg.kline is None
        assert msg.book_ticker is None
        assert msg.trade is None
        assert msg.raw is None

    def test_now_ms_returns_recent_millisecond_timestamp(self):
        """Sanity check: result should be unix ms in the current era.
        Any value < year-2020 ms would indicate a unit bug (seconds vs ms).
        """
        ms = StreamMessage.now_ms()
        # 2020-01-01 in unix ms
        assert ms > 1_577_836_800_000
        # not in the far future
        assert ms < 4_102_444_800_000  # year 2100