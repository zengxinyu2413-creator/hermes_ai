"""
Reusable nautilus instrument constructors for hermes.

⚠️  APPROXIMATE VALUES — NOT PRODUCTION-READY  ⚠️
手搓的 CurrencyPair 字段为近似值,非真实 Binance 规格:
  - min_notional / max_price / max_quantity 是为跑通而填的占位值
  - price/size precision=2 仅按 mainnet stepSize 粗略对齐
生产环境需正式的 BinanceInstrumentProvider。
"""
from __future__ import annotations

from decimal import Decimal

from nautilus_trader.model.currencies import SOL, USDT
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import CurrencyPair
from nautilus_trader.model.objects import Money, Price, Quantity

_BINANCE = Venue("BINANCE")


def make_solusdt_binance() -> CurrencyPair:
    """Return a hand-crafted SOLUSDT CurrencyPair for backtesting.

    ⚠️ Approximate / non-production values — see module docstring.
    """
    return CurrencyPair(
        instrument_id=InstrumentId(Symbol("SOLUSDT"), _BINANCE),
        raw_symbol=Symbol("SOLUSDT"),
        base_currency=SOL,
        quote_currency=USDT,
        price_precision=2,
        size_precision=2,
        price_increment=Price.from_str("0.01"),
        size_increment=Quantity.from_str("0.01"),
        lot_size=None,
        max_quantity=Quantity.from_str("90000.00"),
        min_quantity=Quantity.from_str("0.01"),
        max_notional=None,
        min_notional=Money.from_str("5.00 USDT"),
        max_price=Price.from_str("10000.00"),
        min_price=Price.from_str("0.01"),
        margin_init=Decimal("1.00"),
        margin_maint=Decimal("0.35"),
        maker_fee=Decimal("0.0001"),
        taker_fee=Decimal("0.0001"),
        ts_event=0,
        ts_init=0,
    )
