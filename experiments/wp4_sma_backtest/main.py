# experiments/wp4_sma_backtest/main.py
"""
WP-4 SMA Crossover Backtest
=============================
Flow:
  1. Load testnet credentials from infra/.env
  2. Fetch 1000 x SOLUSDT 1m bars from Binance testnet REST
  3. Convert klines → nautilus Bar via hermes adapter
  4. Build BacktestEngine with SMACrossoverStrategy(fast=10, slow=30)
  5. Run and print: fill count, final PnL, position count

NOT production code — uses approximate SOLUSDT instrument values.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.config import LoggingConfig
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import TraderId, Venue
from nautilus_trader.model.objects import Money

from hermes.adapters.nautilus.binance import build_bar_type, kline_to_bar
from hermes.adapters.nautilus.instruments import make_solusdt_binance
from hermes.exchanges.binance_contracts import KlineInterval
from hermes.exchanges.binance_credentials import BinanceCredentials, BinanceEnvironment
from hermes.exchanges.binance_rest import BinanceRestClient
from hermes.strategies.sma_crossover import SMACrossoverConfig, SMACrossoverStrategy

PRICE_PRECISION = 2
SIZE_PRECISION = 2
KLINE_LIMIT = 1000

_BINANCE = Venue("BINANCE")
ENV_FILE = Path(__file__).resolve().parents[2] / "infra" / ".env"


async def _fetch_klines():
    creds = BinanceCredentials(_env_file=ENV_FILE)
    key, secret = creds.get_key_pair(BinanceEnvironment.TESTNET)
    async with BinanceRestClient(
        api_key=key, api_secret=secret, env=BinanceEnvironment.TESTNET
    ) as client:
        return await client.get_klines("SOLUSDT", KlineInterval.MIN_1, limit=KLINE_LIMIT)


def main() -> None:
    print(f"ENV_FILE: {ENV_FILE}")
    assert ENV_FILE.exists(), f"env file not found: {ENV_FILE}"

    klines = asyncio.run(_fetch_klines())
    print(f"fetched {len(klines)} bars (requested {KLINE_LIMIT})")

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
    print(f"converted {len(bars)} bars")

    instrument = make_solusdt_binance()
    instrument_id = instrument.id

    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id=TraderId("WP4-SMA-001"),
            logging=LoggingConfig(log_level="WARNING"),
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

    config = SMACrossoverConfig(
        instrument_id=instrument_id,
        bar_type=bar_type,
        fast_period=10,
        slow_period=30,
        trade_size="1.00",
    )
    strategy = SMACrossoverStrategy(config)
    engine.add_strategy(strategy)

    print("running backtest ...")
    engine.run()

    result = engine.get_result()

    # --- Key result numbers ---
    print("\n=== WP-4 SMA Backtest Results ===")
    print(f"total_orders:    {result.total_orders}")
    print(f"total_positions: {result.total_positions}")

    usdt_pnl = result.stats_pnls.get("USDT", {})
    pnl_total = usdt_pnl.get("PnL (total)", float("nan"))
    win_rate = usdt_pnl.get("Win Rate", float("nan"))
    print(f"PnL (USDT):      {pnl_total:.4f}")
    print(f"win_rate:        {win_rate:.2%}" if win_rate == win_rate else "win_rate:        n/a")

    if result.total_orders == 0:
        print("\n[INFO] 0 fills — no SMA crossover in the fetched window.")
        print("       Consider fetching more bars (currently requesting 1000).")
    else:
        direction = "PROFIT" if pnl_total > 0 else "LOSS"
        print(f"\nResult: {direction}  ({pnl_total:+.4f} USDT)")


if __name__ == "__main__":
    main()
