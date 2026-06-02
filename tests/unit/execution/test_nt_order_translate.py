"""Tests for nt_order_to_new_order_kwargs — 判据 A~F.

Uses real NT OrderFactory for happy-path orders; types.SimpleNamespace for
edge-case enum values (NO_ORDER_SIDE, STOP_LIMIT, GTD) that the factory
rejects internally.
"""
from __future__ import annotations

import types
from decimal import Decimal

import pytest
from nautilus_trader.common.factories import OrderFactory
from nautilus_trader.model.enums import OrderSide, OrderType, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId, StrategyId, Symbol, TraderId, Venue
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.test_kit.stubs.component import LiveClock

from hermes.core.exceptions import ConfigurationError
from hermes.exchanges.binance_credentials import BinanceEnvironment
from hermes.exchanges.binance_rest import BinanceRestClient
from hermes.execution.nt_order_translate import nt_order_to_new_order_kwargs

_TRADER_ID = TraderId("TESTER-001")
_STRATEGY_ID = StrategyId("TEST-001")
_IID = InstrumentId(Symbol("SOLUSDT"), Venue("BINANCE"))


def _factory() -> OrderFactory:
    return OrderFactory(trader_id=_TRADER_ID, strategy_id=_STRATEGY_ID, clock=LiveClock())


def _fake(side=OrderSide.BUY, order_type=OrderType.MARKET, tif=TimeInForce.GTC,
          qty="1", price=None):
    obj = types.SimpleNamespace(
        side=side,
        order_type=order_type,
        time_in_force=tif,
        quantity=Quantity.from_str(qty),
        instrument_id=_IID,
    )
    if price is not None:
        obj.price = Price.from_str(price)
    return obj


# ---------------------------------------------------------------------------
# 判据 A: MARKET path — dict has no 'price' or 'time_in_force' keys
# ---------------------------------------------------------------------------

class TestJudgeAMarketNoPriceTif:
    def test_market_buy_no_price_key(self) -> None:
        order = _factory().market(_IID, OrderSide.BUY, Quantity.from_str("1.5"))
        kwargs = nt_order_to_new_order_kwargs(order)
        assert "price" not in kwargs
        assert "time_in_force" not in kwargs

    def test_market_sell_no_price_key(self) -> None:
        order = _factory().market(_IID, OrderSide.SELL, Quantity.from_str("0.5"))
        kwargs = nt_order_to_new_order_kwargs(order)
        assert "price" not in kwargs
        assert "time_in_force" not in kwargs


# ---------------------------------------------------------------------------
# 判据 B: side/order_type/tif enum→str mapping complete, no silent fallback
# ---------------------------------------------------------------------------

class TestJudgeBEnumToStrMapping:
    def test_market_buy_side_str(self) -> None:
        order = _factory().market(_IID, OrderSide.BUY, Quantity.from_str("1"))
        assert nt_order_to_new_order_kwargs(order)["side"] == "BUY"

    def test_market_sell_side_str(self) -> None:
        order = _factory().market(_IID, OrderSide.SELL, Quantity.from_str("1"))
        assert nt_order_to_new_order_kwargs(order)["side"] == "SELL"

    def test_market_order_type_str(self) -> None:
        order = _factory().market(_IID, OrderSide.BUY, Quantity.from_str("1"))
        assert nt_order_to_new_order_kwargs(order)["order_type"] == "MARKET"

    def test_limit_order_type_str(self) -> None:
        order = _factory().limit(
            _IID, OrderSide.BUY, Quantity.from_str("1"), Price.from_str("150.00")
        )
        assert nt_order_to_new_order_kwargs(order)["order_type"] == "LIMIT"

    def test_limit_default_tif_is_gtc(self) -> None:
        order = _factory().limit(
            _IID, OrderSide.BUY, Quantity.from_str("1"), Price.from_str("150.00")
        )
        assert nt_order_to_new_order_kwargs(order)["time_in_force"] == "GTC"

    def test_limit_ioc_tif(self) -> None:
        order = _fake(
            order_type=OrderType.LIMIT, tif=TimeInForce.IOC,
            price="150.00",
        )
        assert nt_order_to_new_order_kwargs(order)["time_in_force"] == "IOC"

    def test_limit_fok_tif(self) -> None:
        order = _fake(
            order_type=OrderType.LIMIT, tif=TimeInForce.FOK,
            price="150.00",
        )
        assert nt_order_to_new_order_kwargs(order)["time_in_force"] == "FOK"


# ---------------------------------------------------------------------------
# 判据 C: all Decimal via str(), zero float path
# ---------------------------------------------------------------------------

class TestJudgeCDecimalViaStr:
    def test_quantity_is_decimal(self) -> None:
        order = _factory().market(_IID, OrderSide.BUY, Quantity.from_str("1.5"))
        assert isinstance(nt_order_to_new_order_kwargs(order)["quantity"], Decimal)

    def test_quantity_tiny_formats_without_scientific_notation(self) -> None:
        # format(qty, "f") is what new_order sends to Binance — must not be "1E-8"
        order = _factory().limit(
            _IID, OrderSide.BUY, Quantity.from_str("0.00000001"), Price.from_str("150.00")
        )
        qty = nt_order_to_new_order_kwargs(order)["quantity"]
        assert isinstance(qty, Decimal)
        assert format(qty, "f") == "0.00000001"

    def test_price_is_decimal(self) -> None:
        order = _factory().limit(
            _IID, OrderSide.BUY, Quantity.from_str("1"), Price.from_str("150.25")
        )
        price = nt_order_to_new_order_kwargs(order)["price"]
        assert isinstance(price, Decimal)
        assert price == Decimal("150.25")

    def test_quantity_value_correct(self) -> None:
        order = _factory().market(_IID, OrderSide.BUY, Quantity.from_str("1.5"))
        assert nt_order_to_new_order_kwargs(order)["quantity"] == Decimal("1.5")


# ---------------------------------------------------------------------------
# 判据 D: unknown order_type / side / tif → ValueError (no silent fallback)
# ---------------------------------------------------------------------------

class TestJudgeDUnknownRaisesValueError:
    def test_stop_limit_order_type_raises(self) -> None:
        order = _fake(order_type=OrderType.STOP_LIMIT, price="150.00")
        with pytest.raises(ValueError, match="STOP_LIMIT"):
            nt_order_to_new_order_kwargs(order)

    def test_trailing_stop_market_raises(self) -> None:
        order = _fake(order_type=OrderType.TRAILING_STOP_MARKET)
        with pytest.raises(ValueError, match="TRAILING_STOP_MARKET"):
            nt_order_to_new_order_kwargs(order)

    def test_no_order_side_raises(self) -> None:
        order = _fake(side=OrderSide.NO_ORDER_SIDE)
        with pytest.raises(ValueError, match="NO_ORDER_SIDE"):
            nt_order_to_new_order_kwargs(order)

    def test_limit_gtd_tif_raises(self) -> None:
        order = _fake(order_type=OrderType.LIMIT, tif=TimeInForce.GTD, price="150.00")
        with pytest.raises(ValueError, match="GTD"):
            nt_order_to_new_order_kwargs(order)

    def test_limit_day_tif_raises(self) -> None:
        order = _fake(order_type=OrderType.LIMIT, tif=TimeInForce.DAY, price="150.00")
        with pytest.raises(ValueError, match="DAY"):
            nt_order_to_new_order_kwargs(order)


# ---------------------------------------------------------------------------
# 判据 E: roundtrip — kwargs passes new_order pre-network validation
#   ConfigurationError (not connected) proves validation passed without ValueError
# ---------------------------------------------------------------------------

class TestJudgeERoundtrip:
    async def test_market_buy_passes_new_order_validation(self) -> None:
        order = _factory().market(_IID, OrderSide.BUY, Quantity.from_str("1.5"))
        kwargs = nt_order_to_new_order_kwargs(order)
        client = BinanceRestClient("key", "secret", env=BinanceEnvironment.TESTNET)
        with pytest.raises(ConfigurationError):
            await client.new_order(**kwargs)

    async def test_limit_sell_gtc_passes_new_order_validation(self) -> None:
        order = _factory().limit(
            _IID, OrderSide.SELL, Quantity.from_str("1"), Price.from_str("150.25")
        )
        kwargs = nt_order_to_new_order_kwargs(order)
        client = BinanceRestClient("key", "secret", env=BinanceEnvironment.TESTNET)
        with pytest.raises(ConfigurationError):
            await client.new_order(**kwargs)

    async def test_market_without_price_kwarg_passes_new_order_validation(self) -> None:
        order = _factory().market(_IID, OrderSide.BUY, Quantity.from_str("2"))
        kwargs = nt_order_to_new_order_kwargs(order)
        assert "price" not in kwargs
        client = BinanceRestClient("key", "secret", env=BinanceEnvironment.TESTNET)
        # new_order raises ValueError if price is passed for MARKET — confirms we omit it
        with pytest.raises(ConfigurationError):
            await client.new_order(**kwargs)


# ---------------------------------------------------------------------------
# 判据 F: additional coverage — symbol, full kwargs shape, sell MARKET
# ---------------------------------------------------------------------------

class TestJudgeFAdditional:
    def test_symbol_from_instrument_id(self) -> None:
        order = _factory().market(_IID, OrderSide.BUY, Quantity.from_str("1"))
        assert nt_order_to_new_order_kwargs(order)["symbol"] == "SOLUSDT"

    def test_limit_buy_gtc_full_kwargs_shape(self) -> None:
        order = _factory().limit(
            _IID, OrderSide.BUY, Quantity.from_str("0.060"), Price.from_str("83.70")
        )
        kwargs = nt_order_to_new_order_kwargs(order)
        assert kwargs == {
            "symbol": "SOLUSDT",
            "side": "BUY",
            "order_type": "LIMIT",
            "quantity": Decimal("0.060"),
            "price": Decimal("83.70"),
            "time_in_force": "GTC",
        }

    def test_market_sell_full_kwargs_shape(self) -> None:
        order = _factory().market(_IID, OrderSide.SELL, Quantity.from_str("0.5"))
        kwargs = nt_order_to_new_order_kwargs(order)
        assert set(kwargs.keys()) == {"symbol", "side", "order_type", "quantity"}
        assert kwargs["side"] == "SELL"
        assert kwargs["order_type"] == "MARKET"
