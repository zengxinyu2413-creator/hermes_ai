"""Hermes AI CLI entry point.

Entry point registered in pyproject.toml:
    hermes = "hermes.cli:main"

Subcommands
-----------
trade-live  Launch the live/testnet order-submission node (NT Binance adapter, b3b).

Architecture note (X-path, b3b)
--------------------------------
The self-built execution chain (new_order / nt_order_translate / BinanceLiveExecClient
from b3a / 3b10272) is dormant on the live path: NT's built-in BinanceLiveExecClientFactory
is used directly, bypassing those modules.  The self-built modules are kept and their tests
continue to run; they are not deleted.
"""
from __future__ import annotations

import click
from nautilus_trader.adapters.binance import BinanceExecClientConfig, BinanceLiveExecClientFactory
from nautilus_trader.adapters.binance.common.enums import BinanceAccountType, BinanceEnvironment
from nautilus_trader.live.config import TradingNodeConfig
from nautilus_trader.live.node import TradingNode


@click.group()
def main() -> None:
    """Hermes AI trading system."""


@main.command("trade-live")
@click.option("--dry", is_flag=True, help="Validate config and print summary; no connection.")
def trade_live(dry: bool) -> None:
    """Launch the live/testnet order-submission node.

    Uses NT's built-in Binance adapter (X-path, b3b).  Credentials are read at
    runtime from BINANCE_TESTNET_API_KEY / BINANCE_TESTNET_API_SECRET (not stored
    in config).  --dry exits before TradingNode is constructed; no network connection.
    """
    config = TradingNodeConfig(
        trader_id="TRADER-001",
        exec_clients={
            "BINANCE": BinanceExecClientConfig(
                environment=BinanceEnvironment.TESTNET,  # critical: omitting → LIVE (mainnet)
                account_type=BinanceAccountType.SPOT,
                max_retries=0,  # zero retries on order submission
                # api_key / api_secret left None: NT reads BINANCE_TESTNET_API_KEY/SECRET
            )
        },
    )
    if dry:
        exec_cfg = config.exec_clients["BINANCE"]
        click.echo(
            f"dry-run: config validated — "
            f"env={exec_cfg.environment.value} "
            f"account={exec_cfg.account_type.value} "
            f"max_retries={exec_cfg.max_retries}, no connection"
        )
        return
    node = TradingNode(config=config)
    node.add_exec_client_factory("BINANCE", BinanceLiveExecClientFactory)
    node.build()
    node.run()
