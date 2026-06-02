"""Tests for BinanceLiveExecClient — 判据 A~G.

Strategy: patch LiveExecutionClient.__init__ to bypass NT plumbing;
mocker.patch nt_order_to_new_order_kwargs to decouple from translation layer.
Zero network calls — all rest_client interactions are AsyncMock.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nautilus_trader.live.execution_client import LiveExecutionClient
from nautilus_trader.model.enums import LiquiditySide, OrderSide, OrderType
from nautilus_trader.model.identifiers import (
    ClientId,
    ClientOrderId,
    InstrumentId,
    StrategyId,
    TradeId,
    VenueOrderId,
)

from hermes.core.exceptions import BinanceAPIError
from hermes.exchanges.binance_rest import BinanceRestClient
from hermes.execution.binance_exec_client import BinanceLiveExecClient

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_STRATEGY_ID = StrategyId("S-001")
_IID = InstrumentId.from_str("SOLUSDT.BINANCE")
_COI = ClientOrderId("O-001")

_TRANSLATE_KWARGS: dict = {
    "symbol": "SOLUSDT",
    "side": "BUY",
    "order_type": "MARKET",
    "quantity": Decimal("0.001"),
}

_FILL = {
    "price": "150.25",
    "qty": "0.001",
    "commission": "0.00015025",
    "commissionAsset": "USDT",
    "tradeId": 99999,
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(rest: AsyncMock | None = None) -> tuple[BinanceLiveExecClient, AsyncMock]:
    if rest is None:
        rest = AsyncMock(spec=BinanceRestClient)
    with patch.object(LiveExecutionClient, "__init__", return_value=None):
        client = BinanceLiveExecClient(
            loop=MagicMock(),
            client_id=ClientId("BINANCE"),
            venue=MagicMock(),
            oms_type=MagicMock(),
            account_type=MagicMock(),
            base_currency=None,
            instrument_provider=MagicMock(),
            msgbus=MagicMock(),
            cache=MagicMock(),
            clock=MagicMock(),
            rest_client=rest,
        )
    # _clock is a Cython cdef slot (not writable from Python); mock _now_ns instead
    client._now_ns = MagicMock(return_value=1_000_000_000)  # type: ignore[method-assign]
    client.generate_order_submitted = MagicMock()  # type: ignore[method-assign]
    client.generate_order_accepted = MagicMock()   # type: ignore[method-assign]
    client.generate_order_rejected = MagicMock()   # type: ignore[method-assign]
    client.generate_order_filled = MagicMock()     # type: ignore[method-assign]
    return client, rest


def _make_cmd() -> MagicMock:
    order = MagicMock()
    order.strategy_id = _STRATEGY_ID
    order.instrument_id = _IID
    order.client_order_id = _COI
    order.side = OrderSide.BUY
    order.order_type = OrderType.MARKET
    cmd = MagicMock()
    cmd.order = order
    return cmd


def _resp(status: str = "NEW", fills: list | None = None) -> dict:
    return {
        "orderId": 12345,
        "status": status,
        "transactTime": 1_000,
        "fills": fills or [],
    }


# ---------------------------------------------------------------------------
# 判据 G: _connect / _disconnect call the right rest_client methods
# ---------------------------------------------------------------------------

class TestConnectDisconnect:
    async def test_connect_calls_rest_connect(self) -> None:
        client, rest = _make_client()
        await client._connect()
        rest.connect.assert_called_once()

    async def test_disconnect_calls_rest_aclose(self) -> None:
        client, rest = _make_client()
        await client._disconnect()
        rest.aclose.assert_called_once()


# ---------------------------------------------------------------------------
# 判据 A: _submit_order 三段齐(submitted 前置 / 发单 / 据 status 回报)
# ---------------------------------------------------------------------------

class TestSubmitOrderThreeSegments:
    async def test_submitted_fires_before_network(self, mocker: MagicMock) -> None:
        """generate_order_submitted must fire even if new_order raises."""
        mocker.patch(
            "hermes.execution.binance_exec_client.nt_order_to_new_order_kwargs",
            return_value=_TRANSLATE_KWARGS,
        )
        client, rest = _make_client()
        rest.new_order = AsyncMock(side_effect=BinanceAPIError(-1, "err", 400))
        await client._submit_order(_make_cmd())
        client.generate_order_submitted.assert_called_once()

    async def test_limit_new_submitted_then_accepted_no_fill(self, mocker: MagicMock) -> None:
        mocker.patch(
            "hermes.execution.binance_exec_client.nt_order_to_new_order_kwargs",
            return_value=_TRANSLATE_KWARGS,
        )
        client, rest = _make_client()
        rest.new_order = AsyncMock(return_value=_resp("NEW"))
        await client._submit_order(_make_cmd())
        client.generate_order_submitted.assert_called_once()
        client.generate_order_accepted.assert_called_once()
        client.generate_order_filled.assert_not_called()
        client.generate_order_rejected.assert_not_called()

    async def test_market_filled_submitted_accepted_filled(self, mocker: MagicMock) -> None:
        mocker.patch(
            "hermes.execution.binance_exec_client.nt_order_to_new_order_kwargs",
            return_value=_TRANSLATE_KWARGS,
        )
        client, rest = _make_client()
        rest.new_order = AsyncMock(return_value=_resp("FILLED", fills=[_FILL]))
        await client._submit_order(_make_cmd())
        client.generate_order_submitted.assert_called_once()
        client.generate_order_accepted.assert_called_once()
        client.generate_order_filled.assert_called_once()
        client.generate_order_rejected.assert_not_called()


# ---------------------------------------------------------------------------
# 判据 B: status → event mapping complete
# ---------------------------------------------------------------------------

class TestStatusMapping:
    async def test_status_rejected_fires_rejected_not_accepted(self, mocker: MagicMock) -> None:
        mocker.patch(
            "hermes.execution.binance_exec_client.nt_order_to_new_order_kwargs",
            return_value=_TRANSLATE_KWARGS,
        )
        client, rest = _make_client()
        rest.new_order = AsyncMock(return_value=_resp("REJECTED"))
        await client._submit_order(_make_cmd())
        client.generate_order_rejected.assert_called_once()
        client.generate_order_accepted.assert_not_called()
        client.generate_order_filled.assert_not_called()

    async def test_partially_filled_fires_accepted_and_fill(self, mocker: MagicMock) -> None:
        mocker.patch(
            "hermes.execution.binance_exec_client.nt_order_to_new_order_kwargs",
            return_value=_TRANSLATE_KWARGS,
        )
        client, rest = _make_client()
        rest.new_order = AsyncMock(return_value=_resp("PARTIALLY_FILLED", fills=[_FILL]))
        await client._submit_order(_make_cmd())
        client.generate_order_accepted.assert_called_once()
        client.generate_order_filled.assert_called_once()

    async def test_multiple_fills_generate_multiple_fill_events(self, mocker: MagicMock) -> None:
        mocker.patch(
            "hermes.execution.binance_exec_client.nt_order_to_new_order_kwargs",
            return_value=_TRANSLATE_KWARGS,
        )
        fill2 = {**_FILL, "qty": "0.002", "tradeId": 99998}
        client, rest = _make_client()
        rest.new_order = AsyncMock(return_value=_resp("FILLED", fills=[_FILL, fill2]))
        await client._submit_order(_make_cmd())
        assert client.generate_order_filled.call_count == 2


# ---------------------------------------------------------------------------
# 判据 C: BinanceAPIError captured → rejected (not propagated)
# ---------------------------------------------------------------------------

class TestBinanceAPIErrorHandling:
    async def test_api_error_fires_rejected_not_accepted(self, mocker: MagicMock) -> None:
        mocker.patch(
            "hermes.execution.binance_exec_client.nt_order_to_new_order_kwargs",
            return_value=_TRANSLATE_KWARGS,
        )
        client, rest = _make_client()
        rest.new_order = AsyncMock(
            side_effect=BinanceAPIError(-1013, "Filter failure", 400)
        )
        await client._submit_order(_make_cmd())
        client.generate_order_rejected.assert_called_once()
        client.generate_order_accepted.assert_not_called()

    async def test_api_error_reason_in_rejected_call(self, mocker: MagicMock) -> None:
        mocker.patch(
            "hermes.execution.binance_exec_client.nt_order_to_new_order_kwargs",
            return_value=_TRANSLATE_KWARGS,
        )
        client, rest = _make_client()
        err = BinanceAPIError(-1013, "Filter failure: LOT_SIZE", 400)
        rest.new_order = AsyncMock(side_effect=err)
        await client._submit_order(_make_cmd())
        reason_arg = client.generate_order_rejected.call_args[0][3]
        assert "Filter failure" in reason_arg

    async def test_value_error_from_translate_fires_rejected(self, mocker: MagicMock) -> None:
        mocker.patch(
            "hermes.execution.binance_exec_client.nt_order_to_new_order_kwargs",
            side_effect=ValueError("Unsupported order_type: 'STOP_LIMIT'"),
        )
        client, rest = _make_client()
        await client._submit_order(_make_cmd())
        client.generate_order_rejected.assert_called_once()
        rest.new_order.assert_not_called()


# ---------------------------------------------------------------------------
# 判据 D: venue_order_id / ts_event / fill types correct
# ---------------------------------------------------------------------------

class TestFieldTypes:
    async def test_accepted_receives_venue_order_id(self, mocker: MagicMock) -> None:
        mocker.patch(
            "hermes.execution.binance_exec_client.nt_order_to_new_order_kwargs",
            return_value=_TRANSLATE_KWARGS,
        )
        client, rest = _make_client()
        rest.new_order = AsyncMock(return_value=_resp("NEW"))
        await client._submit_order(_make_cmd())
        venue_order_id_arg = client.generate_order_accepted.call_args[0][3]
        assert isinstance(venue_order_id_arg, VenueOrderId)
        assert venue_order_id_arg == VenueOrderId("12345")

    async def test_fill_trade_id_is_trade_id_type(self, mocker: MagicMock) -> None:
        mocker.patch(
            "hermes.execution.binance_exec_client.nt_order_to_new_order_kwargs",
            return_value=_TRANSLATE_KWARGS,
        )
        client, rest = _make_client()
        rest.new_order = AsyncMock(return_value=_resp("FILLED", fills=[_FILL]))
        await client._submit_order(_make_cmd())
        trade_id_arg = client.generate_order_filled.call_args[0][5]
        assert isinstance(trade_id_arg, TradeId)
        assert trade_id_arg == TradeId("99999")

    async def test_fill_liquidity_side_is_no_liquidity_side(self, mocker: MagicMock) -> None:
        mocker.patch(
            "hermes.execution.binance_exec_client.nt_order_to_new_order_kwargs",
            return_value=_TRANSLATE_KWARGS,
        )
        client, rest = _make_client()
        rest.new_order = AsyncMock(return_value=_resp("FILLED", fills=[_FILL]))
        await client._submit_order(_make_cmd())
        liq_side = client.generate_order_filled.call_args[0][12]
        assert liq_side == LiquiditySide.NO_LIQUIDITY_SIDE

    async def test_transact_time_ms_converted_to_ns(self, mocker: MagicMock) -> None:
        mocker.patch(
            "hermes.execution.binance_exec_client.nt_order_to_new_order_kwargs",
            return_value=_TRANSLATE_KWARGS,
        )
        client, rest = _make_client()
        rest.new_order = AsyncMock(return_value=_resp("NEW"))
        await client._submit_order(_make_cmd())
        ts_arg = client.generate_order_accepted.call_args[0][4]
        # transactTime=1000ms → 1000 * 1_000_000 ns = 1_000_000_000 ns
        assert ts_arg == 1_000 * 1_000_000


# ---------------------------------------------------------------------------
# 判据 E: stub methods raise NotImplementedError
# ---------------------------------------------------------------------------

class TestStubsRaiseNotImplemented:
    async def test_submit_order_list_raises(self) -> None:
        client, _ = _make_client()
        with pytest.raises(NotImplementedError):
            await client._submit_order_list(MagicMock())  # type: ignore[arg-type]

    async def test_cancel_order_raises(self) -> None:
        client, _ = _make_client()
        with pytest.raises(NotImplementedError):
            await client._cancel_order(MagicMock())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 判据 F: nt_order_to_new_order_kwargs called with command.order
# ---------------------------------------------------------------------------

class TestTranslateCalled:
    async def test_translate_called_with_order(self, mocker: MagicMock) -> None:
        mock_translate = mocker.patch(
            "hermes.execution.binance_exec_client.nt_order_to_new_order_kwargs",
            return_value=_TRANSLATE_KWARGS,
        )
        client, rest = _make_client()
        rest.new_order = AsyncMock(return_value=_resp("NEW"))
        cmd = _make_cmd()
        await client._submit_order(cmd)
        mock_translate.assert_called_once_with(cmd.order)

    async def test_translate_kwargs_passed_to_new_order(self, mocker: MagicMock) -> None:
        custom_kwargs: dict = {
            "symbol": "SOLUSDT",
            "side": "SELL",
            "order_type": "LIMIT",
            "quantity": Decimal("0.5"),
            "price": Decimal("155.00"),
            "time_in_force": "GTC",
        }
        mocker.patch(
            "hermes.execution.binance_exec_client.nt_order_to_new_order_kwargs",
            return_value=custom_kwargs,
        )
        client, rest = _make_client()
        rest.new_order = AsyncMock(return_value=_resp("NEW"))
        await client._submit_order(_make_cmd())
        rest.new_order.assert_called_once_with(**custom_kwargs)
