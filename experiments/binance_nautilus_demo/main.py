# experiments/binance_nautilus_demo/main.py
"""
⚠️  ONE-OFF WIRING DEMO — NOT PRODUCTION CODE  ⚠️

验证 Binance→nautilus 数据通路:testnet kline → hermes adapter (kline_to_bar)
→ nautilus Bar → BacktestEngine → strategy.on_bar,断言三方计数一致(通路无丢包)。
保留此文件仅作为"接线方式"的活文档参考。

切勿复用于实盘 / 生产:
  - 手搓的 SOLUSDT CurrencyPair 字段为近似值,非真实 Binance 规格:
    min_notional / max_price / max_quantity 是为跑通而填的占位值,
    price/size precision=2 仅按 mainnet stepSize 粗略对齐。
    生产环境需正式的 BinanceInstrumentProvider(WP-3 step 5 范畴)。
  - 硬编码 testnet env + limit=500,无错误重试 / 无 paper-trading 语义。
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path

from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.config import LoggingConfig
from nautilus_trader.model.currencies import SOL, USDT
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import InstrumentId, Symbol, TraderId, Venue
from nautilus_trader.model.instruments import CurrencyPair
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.trading.strategy import Strategy, StrategyConfig

from hermes.adapters.nautilus.binance import build_bar_type, kline_to_bar
from hermes.exchanges.binance_contracts import KlineInterval
from hermes.exchanges.binance_credentials import BinanceCredentials, BinanceEnvironment
from hermes.exchanges.binance_rest import BinanceRestClient

# ---------------------------------------------------------------------------
# Constants — single source of truth for all precision in this demo
# ---------------------------------------------------------------------------
PRICE_PRECISION = 2
SIZE_PRECISION = 2
KLINE_LIMIT = 500

_BINANCE = Venue("BINANCE")
ENV_FILE = Path(__file__).resolve().parents[2] / "infra" / ".env"


# ---------------------------------------------------------------------------
# Instrument
# ---------------------------------------------------------------------------

def make_solusdt_binance() -> CurrencyPair:
    return CurrencyPair(
        instrument_id=InstrumentId(Symbol("SOLUSDT"), _BINANCE),
        raw_symbol=Symbol("SOLUSDT"),
        base_currency=SOL,
        quote_currency=USDT,
        price_precision=PRICE_PRECISION,
        size_precision=SIZE_PRECISION,
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


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------

class ProbeStrategy(Strategy):
    def __init__(self, config: StrategyConfig, bar_type: BarType) -> None:
        super().__init__(config)
        self._bar_type = bar_type
        self.bar_count = 0

    def on_start(self) -> None:
        self.subscribe_bars(self._bar_type)

    def on_bar(self, bar: Bar) -> None:
        self.bar_count += 1
        self.log.info(
            f"[PROBE] bar #{self.bar_count:>3}  "
            f"close={bar.close}  ts_event={bar.ts_event}"
        )

    def on_stop(self) -> None:
        self.log.info(f"[PROBE] total bars received = {self.bar_count}")


# ---------------------------------------------------------------------------
# Data fetch
# ---------------------------------------------------------------------------

async def _fetch_klines():
    creds = BinanceCredentials(_env_file=ENV_FILE)
    key, secret = creds.get_key_pair(BinanceEnvironment.TESTNET)
    async with BinanceRestClient(
        api_key=key, api_secret=secret, env=BinanceEnvironment.TESTNET
    ) as client:
        return await client.get_klines("SOLUSDT", KlineInterval.MIN_1, limit=KLINE_LIMIT)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"ENV_FILE: {ENV_FILE}")
    assert ENV_FILE.exists(), f"env file not found: {ENV_FILE}"

    klines = asyncio.run(_fetch_klines())

    bar_type = build_bar_type("SOLUSDT", KlineInterval.MIN_1)
    bars = [
        kline_to_bar(
            k,
            bar_type=bar_type,
            price_precision=PRICE_PRECISION,
            size_precision=SIZE_PRECISION,
        )
        for k in klines
    ]

    instrument = make_solusdt_binance()

    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id=TraderId("PROBE-001"),
            logging=LoggingConfig(log_level="INFO"),
        )
    )
    engine.add_venue(
        venue=_BINANCE,
        oms_type=OmsType.NETTING,
        account_type=AccountType.CASH,
        starting_balances=[Money.from_str("100000.00 USDT")],
    )
    engine.add_instrument(instrument)
    engine.add_data(bars)

    strategy = ProbeStrategy(StrategyConfig(), bar_type)
    engine.add_strategy(strategy)
    engine.run()

    print("\n=== 三诊断数字 ===")
    print(f"len(klines):        {len(klines)}")
    print(f"len(bars):          {len(bars)}")
    print(f"strategy.bar_count: {strategy.bar_count}")
    assert len(klines) == len(bars) == strategy.bar_count, (
        f"mismatch — len(klines)={len(klines)}  "
        f"len(bars)={len(bars)}  "
        f"strategy.bar_count={strategy.bar_count}"
    )
    print("断言通过: len(klines) == len(bars) == strategy.bar_count")


if __name__ == "__main__":
    main()
